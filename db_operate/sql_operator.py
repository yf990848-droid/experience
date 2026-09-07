import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, bindparam, case, func, text
from sqlalchemy.exc import SQLAlchemyError

from compress.compress_request import CompressInfoRequest
from db.sql_connector import get_sql_connector
from db_operate.sql_models import (
    SessionRecord, RequestRecord, SessionProperty, LongTextStorage, SessionProcessRecord,
    SessionExtractRecord, CompressedContentRecord, AgentRouterWhitelist, SessionCompression,
    CodeAgentSkill, CodeAgentSessionSummary, CodeAgentDatalog
)
from exception.exceptions import ProjectException
from logger import logger
from project_configs.settings import CST, RESPONSE_BODY_MAX, SESSION_KEEP_KEYS
from utils import decorator
from utils.common_utils import paginate
from utils.decorator import timing_decorator
from utils.token_utils import token_count


class SQLOperator:
    _instance = None

    def __init__(self, connector=None):
        self.connector = connector or get_sql_connector()

    def get_session_record(self, session_id) -> SessionRecord:
        """获取该session对话完成提取的最后index"""
        client = self.connector.client
        try:
            record = client.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()
            return record
        finally:
            client.close()

    def update_session_index(self, session_id, index) -> SessionRecord:
        """更新session对话完成提取的最后index"""
        client = self.connector.client
        try:
            record = client.query(SessionRecord).filter(SessionRecord.session_id == session_id).first()
            if record:
                record.index = index
            else:
                record = SessionRecord(session_id=session_id, index=index)
                client.add(record)
            client.commit()
            client.refresh(record)
            return record
        except SQLAlchemyError as e:
            client.rollback()
            raise
        finally:
            client.close()

    def get_all_sessions(self) -> List[dict]:
        client = self.connector.client
        try:
            records = client.query(SessionProperty).all()
            size_mb = sys.getsizeof(records) / 1024 / 1024
            logger.info(f"records shallow size: {size_mb:.2f} MB")
            return [
                {
                    "session_id": record.session_id,
                    "parent_session_id": record.parent_session_id
                }
                for record in records
            ]
        finally:
            client.close()

    def delete_session(self, session_id):
        client = self.connector.client
        try:
            delete_result = client.query(SessionProperty).filter(SessionProperty.session_id == session_id).delete()
            client.commit()
            if delete_result:
                if delete_result > 0:
                    logger.info(f"delete_session: 成功删除{delete_result}条数据，session_id: {session_id}")
                    return True
            logger.error(f"delete_session: 删除数据失败，session_id: {session_id}")
            return False
        finally:
            client.close()

    def delete_request_record(self, session_id):
        client = self.connector.client
        try:
            delete_result = client.query(SessionRecord).filter(SessionRecord.session_id == session_id).delete()
            client.commit()
            if delete_result:
                if delete_result > 0:
                    logger.info(f"delete_request_record: 成功删除{delete_result}条数据，session_id: {session_id}")
                    return True
            logger.error(f"delete_request_record: 删除数据失败，session_id: {session_id}")
            return False
        finally:
            client.close()

    def delete_expired_request_records(self, before_time: datetime, batch_size: int = 1000):
        client = self.connector.client
        total_deleted = 0
        try:
            while True:
                ids = client.query(RequestRecord.id).filter(
                    RequestRecord.start_time < before_time
                ).limit(batch_size).all()

                if not ids:
                    break

                id_list = [row[0] for row in ids]
                delete_result = client.query(RequestRecord).filter(
                    RequestRecord.id.in_(id_list)
                ).delete(synchronize_session=False)
                client.commit()
                total_deleted += delete_result or 0

            logger.info(f"delete_expired_request_records: 共删除{total_deleted}条数据")
            return total_deleted > 0
        except Exception as e:
            client.rollback()
            logger.error(f"delete_expired_request_records 异常: {e}")
            raise
        finally:
            client.close()

    def delete_long_text_storage(self, hash_code):
        client = self.connector.client
        try:
            delete_result = client.query(LongTextStorage).filter(LongTextStorage.hash_code == hash_code).delete()
            client.commit()
            if delete_result:
                if delete_result > 0:
                    logger.info(f"delete_request_record: 成功删除{delete_result}条数据，hash_code: {hash_code}")
                    return True
            logger.error(f"delete_request_record: 删除数据失败，hash_code: {hash_code}")
            return False
        finally:
            client.close()

    def get_whitelist(self, user_id: str) -> List[str]:
        client = self.connector.client
        try:
            record = client.query(AgentRouterWhitelist).filter(AgentRouterWhitelist.user_id == user_id).first()
            return record
        finally:
            client.close()

    def add_request_record(
            self, request_id, url, request_method, input_data, is_success, output_data, start_time, end_time
    ):
        """记录每一次请求的出入参、成功/失败状态，响应时长等信息"""
        client = self.connector.client
        try:
            record = RequestRecord(
                id=request_id,
                url=url,
                request_method=request_method,
                input=input_data,
                is_success=is_success,
                output=output_data,
                start_time=start_time,
                end_time=end_time,
                cost_time=(end_time - start_time).total_seconds()
            )
            client.add(record)
            client.commit()
            return record
        except SQLAlchemyError as e:
            client.rollback()
            raise
        finally:
            client.close()

    @timing_decorator()
    def session_initial(
            self, *, session_id: str, agent_id: str, agent_name: str, agent_description: str, parent_session_id: str
    ):
        """初始化一个session对话（存在则更新，否则插入）"""
        try:
            with self.connector.client as db:
                record = db.query(SessionProperty).filter(SessionProperty.session_id == session_id).first()

                if record:
                    # 存在，更新字段
                    record.agent_id = agent_id
                    record.agent_name = agent_name
                    record.agent_description = agent_description
                    record.parent_session_id = parent_session_id
                else:
                    # 不存在，插入新记录
                    record = SessionProperty(
                        session_id=session_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        agent_description=agent_description,
                        parent_session_id=parent_session_id,
                    )
                    db.add(record)

                db.commit()
                return record

        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    @decorator.not_none_lru_cache(maxsize=128, ttl=120)
    @timing_decorator()
    def get_session_property(self, session_id: str) -> SessionProperty:
        """获取session属性"""
        try:
            with self.connector.client as db:
                record = db.query(SessionProperty).filter(SessionProperty.session_id == session_id).first()
                return record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def add_long_text_param(self, hash_code: str, content: str, session_id: str = None):
        """保存长文本参数"""
        try:
            with self.connector.client as db:
                record = db.query(LongTextStorage).filter(LongTextStorage.hash_code == hash_code).first()
                # 存在则更新，否则插入
                if record:
                    record.text = content
                    record.session_id = session_id if session_id else record.session_id
                else:
                    record = LongTextStorage(hash_code=hash_code, text=content, session_id=session_id)
                    db.add(record)
                db.commit()
                db.refresh(record)
                return record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    @decorator.not_none_lru_cache(maxsize=128, ttl=120)
    def get_long_text_param(self, hash_code: str):
        """通过哈希值获取长文本参数"""
        try:
            with self.connector.client as db:
                record = db.query(LongTextStorage).filter(LongTextStorage.hash_code == hash_code).first()
                if not record:
                    raise ProjectException(ProjectException.DATA_NOT_EXISTS_ERROR)
                record.last_accessed_at = datetime.utcnow()
                db.commit()
                return record.text
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    @timing_decorator()
    def get_session_process_record(self, session_id: str):
        """获取session的流程信息记录"""
        try:
            with self.connector.client as db:
                record = db.query(SessionProcessRecord) \
                    .filter(SessionProcessRecord.session_id == session_id) \
                    .order_by(SessionProcessRecord.index.desc()).first()
            if record:
                return record
            else:
                return SessionProcessRecord(
                    session_id=session_id, index=0, process_description="", merge_process_descriptions=""
                )
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def add_session_process_record(
            self, session_id: str, index: int, process_description: str, merge_process_descriptions: str
    ):
        """添加session的流程信息记录"""
        try:
            with self.connector.client as db:
                new_record = SessionProcessRecord(
                    session_id=session_id,
                    index=index,
                    process_description=process_description,
                    merge_process_descriptions=merge_process_descriptions
                )
                db.add(new_record)
                db.commit()
                db.refresh(new_record)
                return new_record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常add_session_process_record：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def add_session_extract_record(
            self, *, session_id: str, task_type: str, index_start: int, index_end: int, is_success: bool,
            data: Optional[str] = None, error_msg: Optional[str] = None, start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None
    ):
        """记录提取任务是否成功"""
        try:
            with self.connector.client as db:
                new_record = SessionExtractRecord(
                    session_id=session_id,
                    task_type=task_type,
                    index_start=index_start,
                    index_end=index_end,
                    is_success=is_success,
                    data=data if is_success else None,
                    error_msg=error_msg if not is_success else None,
                    start_time=start_time,
                    end_time=end_time
                )
                db.add(new_record)
                db.commit()
                db.refresh(new_record)
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常add_session_extract_record：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def get_session_id_by_agent_id(
            self, agent_id: str, page_size: int, cur_page_id: int
    ):
        """通过agent_id查询关联的所有session_id列表

        Args:
            agent_id: 要查询的agent标识
            page_size: 单页展示长度

        Returns:
            匹配该agent_id的所有session_id列表
        """
        try:
            # 分页查询入参校验
            if page_size <= 0:
                raise ValueError("page_size需为正整数")
            if cur_page_id < 1:
                raise ValueError("页码编号从1开始")
            with self.connector.client as db:
                # 查询所有匹配的记录并提取session_id字段
                records = db.query(SessionProperty.session_id).filter(
                    SessionProperty.agent_id == agent_id
                ).all()
                agent_id_lst = [record.session_id for record in records]
                # agent_id总数
                total_num = len(agent_id_lst)
                # 分页
                if total_num % page_size != 0:
                    max_page_id = total_num // page_size + 1
                else:
                    max_page_id = total_num // page_size
                if cur_page_id > max_page_id:
                    raise ValueError("cur_page_id过大")
                if total_num <= page_size:
                    page_size = total_num
                agent_id_pages = paginate(agent_id_lst, page_size)

                return {
                    "total_num": total_num,
                    "agent_ids_cur_page": agent_id_pages[cur_page_id - 1]
                }

        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常get_session_id_by_agent_id: {e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)
        except ValueError as e:
            logger.error(f"分页查询入参错误get_session_id_by_agent_id: {e}")
            raise ProjectException(ProjectException.PAGE_QUERY_ERROR)

    def add_compress_record(
            self, session_id: str, compress_content_id: str,
            compress_info: CompressInfoRequest, start_time, end_time
    ):
        try:
            with self.connector.client as db:
                compress_content_record = CompressedContentRecord(
                    compress_content_id=compress_content_id,
                    session_id=session_id,
                    content=compress_info.content,
                    content_type=compress_info.content_type,
                    sub_content_type=compress_info.sub_content_type,
                    compress_content=compress_info.compress_content,
                    summary=compress_info.summary,
                    is_success=compress_info.is_success,
                    error_msg=compress_info.error_msg,
                    start_time=start_time,
                    end_time=end_time,
                    cost_time=(end_time - start_time).total_seconds(),
                    content_token_count=token_count(compress_info.content),
                    compress_token_count=token_count(compress_info.summary + compress_info.compress_content),
                )
                db.add(compress_content_record)
                db.commit()
                db.refresh(compress_content_record)
                return compress_content_record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常add_session_process_record：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def get_compress_record(self, compress_content_id: str) -> Optional[CompressedContentRecord]:
        try:
            with self.connector.client as db:
                record = db.query(CompressedContentRecord).filter(
                    CompressedContentRecord.compress_content_id == compress_content_id).first()
                return record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常add_session_process_record：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    # 压缩记录相关操作

    def save_compression_record(self, record_data: Dict[str, Any]) -> SessionCompression:
        """保存压缩记录"""
        client = self.connector.client
        try:
            record = SessionCompression(
                session_id=record_data["session_id"],
                user_id=record_data["user_id"],
                compression_time=record_data["compression_time"],
                original_token_count=record_data["original_token_count"],
                compressed_token_count=record_data["compressed_token_count"],
                compression_ratio=record_data["compression_ratio"],
                messages_compressed_count=record_data["messages_compressed_count"],
                messages_kept_count=record_data["messages_kept_count"],
                kept_messages_start_index=record_data["kept_messages_start_index"],
                compressed_summary=record_data["compressed_summary"],
                status=record_data["status"],
                error_message=record_data.get("error_message", ""),
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            client.add(record)
            client.commit()
            client.refresh(record)
            return record
        except SQLAlchemyError as e:
            client.rollback()
            raise
        finally:
            client.close()

    def get_compression_by_id(self, record_id: int) -> Optional[SessionCompression]:
        """根据 ID 获取压缩记录"""
        client = self.connector.client
        try:
            record = client.query(SessionCompression).filter(
                SessionCompression.id == record_id
            ).first()
            return record
        finally:
            client.close()

    def update_compression_record(
            self,
            record_id: int,
            update_data: Dict[str, Any]
    ) -> bool:
        """更新压缩记录（通用更新方法）"""
        client = self.connector.client
        try:
            # 添加 updated_at
            update_data["updated_at"] = datetime.now()

            updated = client.query(SessionCompression).filter(
                SessionCompression.id == record_id
            ).update(update_data)
            client.commit()
            return updated > 0
        except SQLAlchemyError as e:
            client.rollback()
            raise
        finally:
            client.close()

    def delete_compression_record(self, record_id: int) -> bool:
        """删除压缩记录"""
        client = self.connector.client
        try:
            deleted = client.query(SessionCompression).filter(
                SessionCompression.id == record_id
            ).delete()
            client.commit()
            return deleted > 0
        except SQLAlchemyError as e:
            client.rollback()
            raise
        finally:
            client.close()

    def get_latest_compression_by_session(
            self,
            session_id: str,
            exclude_status: Optional[list[str]] = None
    ):
        client = self.connector.client
        try:
            query = client.query(SessionCompression).filter(
                SessionCompression.session_id == session_id
            )

            if exclude_status:
                for status in exclude_status:
                    query = query.filter(SessionCompression.status != status)

            return query.order_by(SessionCompression.id.desc()).first()
        finally:
            client.close()

    def get_compression_by_status(
            self,
            session_id: str,
            status: str
    ) -> Optional[SessionCompression]:
        """获取指定 session 指定状态的最新压缩结果"""
        client = self.connector.client
        try:
            record = client.query(SessionCompression).filter(
                SessionCompression.session_id == session_id,
                SessionCompression.status == status
            ).order_by(SessionCompression.id.desc()).first()
            return record
        finally:
            client.close()

    def update_compression_status(
            self,
            session_id: str,
            from_status: str,
            to_status: str
    ) -> bool:
        """更新压缩记录状态"""
        client = self.connector.client
        try:
            updated = client.query(SessionCompression).filter(
                SessionCompression.session_id == session_id,
                SessionCompression.status == from_status
            ).update({
                "status": to_status,
                "updated_at": datetime.now()
            })
            client.commit()
            return updated > 0
        except SQLAlchemyError as e:
            client.rollback()
            raise
        finally:
            client.close()

    def stream_experience_request_rows(
            self,
            start_time: datetime,
            end_time: datetime,
            url_like: str = "%/memory/experience/doc%",
            batch_size: int = 1000,
    ):
        """
        流式拉取时间范围内经验相关接口的请求记录, 只取统计所需列。
        以 start_time 作为请求发生时间过滤。生成器, 请一次性消费完。
        """
        client = self.connector.client
        try:
            query = (
                client.query(
                    RequestRecord.url,
                    RequestRecord.request_method,
                    RequestRecord.input,
                    RequestRecord.is_success,
                )
                .filter(
                    RequestRecord.start_time >= start_time,
                    RequestRecord.start_time < end_time,
                    RequestRecord.url.like(url_like),
                )
            )
            for row in query.yield_per(batch_size):
                yield row.url, row.request_method, row.input, row.is_success
        finally:
            client.close()

    def upsert_skill(self, skill: dict):
        """skill 上传落库(存在则更新,否则插入)"""
        try:
            with self.connector.client as db:
                record = db.query(CodeAgentSkill).filter(
                    CodeAgentSkill.skill_id == skill["skill_id"]
                ).first()
                if record:
                    record.skill_name = skill.get("skill_name")
                    record.description = skill.get("description")
                    record.employee_id = skill.get("employee_id")
                    record.session_id = skill.get("session_id")
                    record.first_input = skill.get("first_input")
                    record.ide_type = skill.get("ide_type")
                    record.remote_git_repo_path = skill.get("remote_git_repo_path")
                    record.archive_name = skill.get("archive_name")
                    record.archive_data = skill.get("archive_data")
                    record.archive_size = skill.get("archive_size")
                    record.first_trace_time = skill.get("first_trace_time")
                    record.etl_load_time = datetime.now(CST).replace(tzinfo=None)
                else:
                    record = CodeAgentSkill(
                        etl_load_time=datetime.now(CST).replace(tzinfo=None),
                        **skill
                    )
                    db.add(record)
                db.commit()
                db.refresh(record)
                return record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常:{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def get_session_summary(self, session_id: str):
        """按 session_id 查 summary，给 skill 落库回填 ide / 第一个 input / 代码仓"""
        try:
            with self.connector.client as db:
                return db.query(CodeAgentSessionSummary).filter(
                    CodeAgentSessionSummary.session_id == session_id
                ).first()
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常:{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def get_day_session_ids(self, day: str, model=CodeAgentDatalog) -> list:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        day_start, day_end = day, (d + timedelta(days=1)).isoformat()
        try:
            with self.connector.client as db:
                rows = db.query(model.session_id).filter(
                    model.session_action_time >= day_start,
                    model.session_action_time < day_end,
                ).distinct().all()
                return [r.session_id for r in rows]
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def get_session_rows(self, session_id: str, model=CodeAgentDatalog) -> list:
        """某个 session 的全部相关行（跨天），时间有序"""

        try:
            with self.connector.client as db:
                return db.query(model).filter(
                    model.session_id == session_id,
                    model.attribute_key.in_(SESSION_KEEP_KEYS),
                ).order_by(
                    model.session_action_time,
                    model.trace_id,
                    model.span_id,
                    model.pk_id,
                ).all()
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def upsert_session_summary(self, summary: dict):
        """合成结果落库（存在则更新，否则插入）"""
        try:
            with self.connector.client as db:
                record = db.query(CodeAgentSessionSummary).filter(
                    CodeAgentSessionSummary.session_id == summary["session_id"]
                ).first()
                if record:
                    record.user_id = summary["user_id"]
                    record.first_trace_time = summary["first_trace_time"]
                    record.conversation_history = summary["conversation_history"]
                    record.first_input = summary["first_input"]  # 新增
                    record.ide_type = summary["ide_type"]  # 新增
                    record.remote_git_repo_path = summary["remote_git_repo_path"]  # 新增
                    record.used_skill = summary["used_skill"]
                    record.is_problem = summary["is_problem"]
                    record.session_date = summary["session_date"]
                    record.source = summary["source"]  # 新增
                    record.etl_load_time = datetime.now(CST)
                    record.prompt_count = summary["prompt_count"]
                else:
                    record = CodeAgentSessionSummary(etl_load_time=datetime.now(CST), **summary)
                    db.add(record)
                db.commit()
                db.refresh(record)
                return record
        except SQLAlchemyError as e:
            logger.error(f"数据库操作异常：{e}")
            raise ProjectException(ProjectException.DB_OPERATION_ERROR)

    def get_session_rows_bulk(self, session_ids: list, model=CodeAgentDatalog,
                              _depth: int = 0) -> dict:
        """流式拉一批 session 的行；OOM 时对半拆分重试。"""
        if not session_ids:
            return {}

        value_col = case(
            (model.attribute_key == "response_body",
             func.substr(model.attribute_value, 1, RESPONSE_BODY_MAX + 1)),
            else_=model.attribute_value,
        ).label("attribute_value")

        try:
            out = defaultdict(list)
            with self.connector.client as db:
                q = db.query(
                    model.pk_id, model.session_id, model.user_id, model.trace_id,
                    model.span_id, model.attribute_key, value_col, model.session_action_time,
                ).filter(
                    model.session_id.in_(session_ids),
                    model.attribute_key.in_(SESSION_KEEP_KEYS),
                ).execution_options(stream_results=True, max_row_buffer=500)
                # 不再 ORDER BY：build_session_summary 内部自己排序，省掉服务端大排序

                for r in q.yield_per(500):
                    out[r.session_id].append(r)
            return dict(out)
        except (SQLAlchemyError, MemoryError) as e:
            if len(session_ids) > 1 and _depth < 8:
                mid = len(session_ids) // 2
                left = self.get_session_rows_bulk(session_ids[:mid], model, _depth + 1)
                right = self.get_session_rows_bulk(session_ids[mid:], model, _depth + 1)
                left.update(right)
                return left
            # 已经拆到单条还失败：记日志跳过，别 raise
            logger.error("session=%s 拉取失败，跳过：%s", session_ids[0] if session_ids else "?", e)
            return {}

    def bulk_upsert_session_summary(self, summaries: list):
        """一批 summary 一次写：1 次 SELECT + 1 次批量 INSERT + 1 次批量 UPDATE + 1 次 commit。
        故意不用 PG 的 ON CONFLICT——你的方言把版本伪装成 9.2，ON CONFLICT 是 9.5 才有的，
        有踩坑风险。这种写法在 GaussDB 上一定能跑。"""
        if not summaries:
            return
        now = datetime.now(CST)
        try:
            with self.connector.client as db:
                ids = [s["session_id"] for s in summaries]
                q = (
                    db.query(CodeAgentSessionSummary.session_id)
                    .filter(CodeAgentSessionSummary.session_id.in_(ids))
                )
                existing = {r[0] for r in q.all()}
                to_insert, to_update = [], []
                for s in summaries:
                    m = {**s, "etl_load_time": now}
                    (to_update if s["session_id"] in existing else to_insert).append(m)

                if to_insert:
                    db.bulk_insert_mappings(CodeAgentSessionSummary, to_insert)
                if to_update:
                    db.bulk_update_mappings(CodeAgentSessionSummary, to_update)
                db.commit()
        except SQLAlchemyError as e:
            # 整批失败时降级为逐条写，避免一条脏数据连累整批
            logger.warning(f"批量写 summary 失败，降级逐条：{e}")
            for s in summaries:
                try:
                    self.upsert_session_summary(s)
                except Exception as e2:
                    logger.error(f"session={s['session_id']} 单条写入失败：{e2}")

    def get_session_sizes(self, session_ids: list, model=CodeAgentDatalog) -> dict:
        """返回 {session_id: (row_count, total_bytes)}，用于跳过超大 session。"""
        if not session_ids:
            return {}
        try:
            with self.connector.client as db:
                rows = db.query(
                    model.session_id,
                    func.count().label("cnt"),
                    func.sum(func.length(model.attribute_value)).label("total"),
                ).filter(
                    model.session_id.in_(session_ids),
                    model.attribute_key.in_(SESSION_KEEP_KEYS),
                ).group_by(model.session_id).all()
            return {r.session_id: (r.cnt, r.total or 0) for r in rows}
        except SQLAlchemyError as e:
            logger.error(f"称重查询失败：{e}")
            return {}  # 称重失败就不过滤，按原逻辑硬拉（有兜底跳过保护）
