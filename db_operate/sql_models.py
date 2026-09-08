from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, \
    PrimaryKeyConstraint, Index, Float, TIMESTAMP, BigInteger, DECIMAL, LargeBinary
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import declarative_base, sessionmaker, Session, Mapped, mapped_column
from sqlalchemy.inspection import inspect
from sqlalchemy.sql import func


# ORM 基类
class BaseModel:
    def to_dict(self):
        return {
            c.key: getattr(self, c.key)
            for c in inspect(self).mapper.column_attrs
        }


Base = declarative_base(cls=BaseModel)


class SessionCompression(Base):
    """会话压缩记录表"""
    __tablename__ = "agent_memory_session_compressions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(128), primary_key=False, index=True)
    user_id = Column(String(128))

    compression_time = Column(DateTime)
    original_token_count = Column(Integer)
    compressed_token_count = Column(Integer)
    compression_ratio = Column(DECIMAL(5, 4))

    messages_compressed_count = Column(Integer)
    messages_kept_count = Column(Integer)
    kept_messages_start_index = Column(Integer)

    compressed_summary = Column(Text)

    status = Column(String(32))
    error_message = Column(String(1024))

    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class SessionRecord(Base):
    """记录session记忆提取到第几轮对话"""
    __tablename__ = 'agent_memory_session_records'

    session_id = Column(String(64), primary_key=True)
    index = Column(Integer, default=0)
    update_time = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<agent_memory_session_records(session_id='{self.session_id}'," \
               f" index={self.index}, update_time={self.update_time})>"


class SessionExtractRecord(Base):
    """记录每轮对话提取是否成功，失败的错误信息是什么"""
    __tablename__ = 'agent_memory_session_extract_records'

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64))
    task_type = Column(String(64))
    index_start = Column(Integer)
    index_end = Column(Integer)
    is_success = Column(Boolean)
    data = Column(Text, comment="提取结果")
    error_msg = Column(Text, comment="提取错误信息")
    start_time = Column(DateTime)
    end_time = Column(DateTime)

    # 设置联合索引
    __table_args__ = (
        Index('idx_session_id_task_type', session_id, task_type),
    )

    def __repr__(self):
        return f"<agent_memory_session_extract_records(session_id='{self.session_id}', index={self.index}, " \
               f"is_success={self.is_success}, data='{self.data}', error_msg='{self.error_msg}', " \
               f"start_time={self.start_time}, end_time={self.end_time})>"


class RequestRecord(Base):
    """记录每一次请求的出入参、成功/失败状态，响应时长等信息"""
    __tablename__ = "agent_memory_request_records"

    id = Column(String(64), primary_key=True)
    url = Column(String(256))
    request_method = Column(String(10))
    input = Column(Text)
    output = Column(Text, comment="方法输出/异常信息")
    is_success = Column(Boolean)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    cost_time = Column(Float)

    def __repr__(self):
        return f"<agent_memory_request_records(id='{self.id}input='{self.input}', is_success={self.is_success}, " \
               f"output='{self.output}', start_time={self.start_time}, end_time={self.end_time})>"


class SessionProperty(Base):
    """session初始化时，记录其属性的表"""
    __tablename__ = "agent_memory_session_properties"

    session_id = Column(String(64), primary_key=True)
    agent_id = Column(String(64))
    agent_name = Column(String(128))
    agent_description = Column(String(256))
    parent_session_id = Column(String(64))


class LongTextStorage(Base):
    __tablename__ = "agent_memory_long_text_storage"

    hash_code = Column(String(64), primary_key=True)
    session_id = Column(String(64))
    text = Column(Text)
    create_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_accessed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<LongTextStorage(hash_code={self.hash_code}, last_accessed_at={self.last_accessed_at})>"


class AgentRouterWhitelist(Base):
    __tablename__ = "agent_router_whitelist"

    user_id = Column(String(64), primary_key=True)
    note = Column(String(64))

    def __repr__(self):
        return f"<AgentRouterWhitelist(user_id={self.user_id}>"


class SessionProcessRecord(Base):
    """记录Session提取的流程信息"""
    __tablename__ = "agent_memory_session_process_records"

    session_id = Column(String(64))
    index = Column(Integer)
    process_description = Column(Text)
    merge_process_descriptions = Column(Text)

    __table_args__ = (
        PrimaryKeyConstraint('session_id', 'index'),
    )

    def __repr__(self):
        return f"<SessionProcessRecord(session_id='{self.session_id}', index={self.index}, " \
               f"process_description={self.process_description})"


class CompressedContentRecord(Base):
    """记录压缩内容的元信息和处理状态"""
    __tablename__ = "agent_memory_compress_records"

    compress_content_id = Column(String(64), primary_key=True, comment="压缩内容唯一ID（关联ES中的切片）")
    session_id = Column(String(64), nullable=False, index=True, comment="会话唯一标识（关联业务会话）")
    content = Column(Text, nullable=False, comment="原始文本内容（可压缩存储）")
    content_type = Column(String(16), nullable=False, comment="文本类型")
    sub_content_type = Column(String(16), nullable=True, comment="文本子类型")
    compress_content = Column(Text, comment="压缩后的摘要内容（JSON或文本）")
    summary = Column(Text, comment="总结的内容")
    is_success = Column(Boolean, comment="是否成功，是为True，否为False")
    error_msg = Column(Text, comment="失败信息")
    start_time = Column(DateTime, nullable=False, comment="压缩开始时间（精确到毫秒）")
    end_time = Column(DateTime, comment="压缩结束时间（精确到毫秒）")
    cost_time = Column(Integer, comment="处理耗时（毫秒）")
    content_token_count = Column(Integer, nullable=False, comment="原始内容token数")
    compress_token_count = Column(Integer, comment="压缩后内容token数")
    created_at = Column(TIMESTAMP, server_default=func.now(), comment="记录创建时间")
    updated_at = Column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now(),
        comment="记录更新时间"
    )

    __table_args__ = (
        Index('idx_session', 'session_id'),
        {'comment': '压缩内容记录表'},
    )

    def __repr__(self):
        return f"<CompressedContentRecord(compress_content_id='{self.compress_content_id}', " \
               f"session_id='{self.session_id}', content_type='{self.content_type}', " \
               f"is_success={self.is_success})>"


class ExperienceVersionHistory(Base):
    """经验文档版本历史表"""
    __tablename__ = "agent_memory_experience_version_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="主文档ID，关联ES中的doc")
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="该快照的版本号")

    # 快照内容（不向量化，纯文本存储）
    title: Mapped[Optional[str]] = mapped_column(Text, comment="标题快照")
    summary: Mapped[Optional[str]] = mapped_column(Text, comment="摘要快照")
    experience: Mapped[Optional[str]] = mapped_column(Text, comment="经验内容快照")
    rag_search_text: Mapped[Optional[str]] = mapped_column(Text, comment="RAG检索文本快照")

    # 元信息
    scene_id: Mapped[Optional[str]] = mapped_column(String(128), comment="场景ID")
    scene: Mapped[Optional[str]] = mapped_column(String(128), comment="场景")
    user_id: Mapped[Optional[str]] = mapped_column(String(128), comment="用户ID")

    # 质量信息
    quality: Mapped[Optional[bool]] = mapped_column(Boolean, comment="质量检查结果")
    quality_category: Mapped[Optional[str]] = mapped_column(String(64), comment="质量分类")
    quality_reason: Mapped[Optional[str]] = mapped_column(Text, comment="质量原因")

    # 扩展字段（JSON 文本）
    product: Mapped[Optional[str]] = mapped_column(Text, comment="产品信息JSON")
    metadata_json: Mapped[Optional[str]] = mapped_column("metadata", Text, comment="元数据JSON")
    log: Mapped[Optional[str]] = mapped_column(Text, comment="日志JSON")

    # 变更审计
    action_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="变更类型: updated/deleted/merged/rollback",
    )

    # 时间戳
    snapshot_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="该版本原始创建时间")
    snapshot_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="该版本生效时间")
    archived_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="归档时间",
    )

    __table_args__ = (
        Index("idx_doc_id_version", "doc_id", "version"),
        Index("idx_archived_at", "archived_at"),
        {"comment": "经验文档版本历史表"},
    )

    def __repr__(self):
        return (
            f"<ExperienceVersionHistory(doc_id='{self.doc_id}', "
            f"version={self.version}, action_type='{self.action_type}')>"
        )

class CodeAgentSkill(Base):
    """扶摇 Skill 市场:整个 skill 目录以 zip 形式存库"""
    __tablename__ = "datalake_code_agent_flywheel_skill"

    skill_id: Mapped[str] = mapped_column(String(128), primary_key=True, comment="skill 唯一标识")
    skill_name: Mapped[Optional[str]] = mapped_column(String(256), comment="skill 名称")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="skill 描述")
    employee_id: Mapped[Optional[str]] = mapped_column(String(64), comment="提交工号")
    session_id: Mapped[Optional[str]] = mapped_column(String(128), comment="来源 session 标识")
    first_input: Mapped[Optional[str]] = mapped_column(Text, comment="用户第一个 input")
    ide_type: Mapped[Optional[str]] = mapped_column(String(128), comment="IDE 类型")
    remote_git_repo_path: Mapped[Optional[str]] = mapped_column(Text, comment="代码仓地址")
    first_trace_time: Mapped[Optional[str]] = mapped_column(String(32), comment="session 最早出现时间")
    archive_name: Mapped[Optional[str]] = mapped_column(String(256), comment="压缩包文件名")
    archive_data: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary().with_variant(LONGBLOB, "mysql"), comment="skill 目录打包(zip)二进制"
    )
    archive_size: Mapped[Optional[int]] = mapped_column(Integer, comment="压缩包字节数")
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="gui", comment="数据来源（gui/cli/...）"
    )
    etl_load_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, comment="写入时间")

    __table_args__ = (
        Index("idx_cas_employee_id", "employee_id"),
        Index("idx_cas_session_id", "session_id"),
        {"comment": "code-agent flywheel skill 市场表"},
    )
class _CodeAgentDatalogColumns:
    """GUI / CLI datalog 两张表的公共列（抽象 mixin）"""
    pk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(128))
    user_id: Mapped[Optional[str]] = mapped_column(Text, comment="用户标识")
    trace_id: Mapped[Optional[str]] = mapped_column(String(128))
    span_id: Mapped[Optional[str]] = mapped_column(String(128))
    attribute_key: Mapped[Optional[str]] = mapped_column(String(64))
    attribute_value: Mapped[Optional[str]] = mapped_column(Text)
    session_action_time: Mapped[Optional[str]] = mapped_column(String(32))


class CodeAgentDatalog(_CodeAgentDatalogColumns, Base):
    __tablename__ = "datalake_code_agent_flywheel_datalog_gui"      # 按你现在的实际表名


class CodeAgentDatalogCli(_CodeAgentDatalogColumns, Base):
    __tablename__ = "datalake_code_agent_flywheel_datalog_cli"


class CodeAgentSessionSummary(Base):
    """每个 session 合成一条的治理结果表"""
    __tablename__ = "datalake_code_agent_flywheel_session_summary"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True, comment="session 标识")
    user_id: Mapped[Optional[str]] = mapped_column(String(128), comment="用户标识")
    first_trace_time: Mapped[Optional[str]] = mapped_column(String(32), comment="session 最早出现时间")
    conversation_history: Mapped[Optional[str]] = mapped_column(Text, comment="对话历史全文")
    first_input: Mapped[Optional[str]] = mapped_column(Text, comment="用户第一个 input")
    ide_type: Mapped[Optional[str]] = mapped_column(String(128), comment="IDE 类型")
    remote_git_repo_path: Mapped[Optional[str]] = mapped_column(Text, comment="代码仓地址")
    used_skill: Mapped[Optional[bool]] = mapped_column(Boolean, comment="是否使用过任意 skill")
    prompt_count: Mapped[Optional[int]] = mapped_column(Integer, comment="用户 prompt 条数")
    is_problem: Mapped[Optional[bool]] = mapped_column(Boolean, comment="对话历史非 prompt 开头则为 True")
    session_date: Mapped[Optional[str]] = mapped_column(String(16), comment="处理批次日期")
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="gui", comment="数据来源（gui/cli/...）"
    )
    etl_load_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, comment="写入时间")

    __table_args__ = (
        Index("idx_css_session_date", "session_date"),
        {"comment": "code-agent flywheel session 汇总表"},
    )



class TraceExperienceJobState(Base):
    """每个运行范围的增量读取位置。"""
    __tablename__ = 'trace_experience_job_state'
    job_name = Column(String(64), primary_key=True)
    range_start = Column(DateTime, nullable=False)
    range_end = Column(DateTime)
    last_update_time = Column(DateTime, nullable=False)
    last_id = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TraceExperienceRecord(Base):
    """一组 case_id + 原始用户的处理进度及待写入结果。"""
    __tablename__ = 'trace_experience_record'
    record_key = Column(String(64), primary_key=True)
    job_name = Column(String(64), nullable=False)
    trace_key = Column(String(64), nullable=False)
    case_id = Column(Text, nullable=False)
    source_test_user_json = Column(Text, nullable=False)
    processed_trace_hash = Column(String(64))
    source_update_time = Column(DateTime)
    experience_refs = Column(Text, nullable=False, default='[]')
    process_status = Column(String(16), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index('idx_trace_job_status_updated', 'job_name', 'process_status', 'updated_at'),)


def init_sql():
    """创建所有表"""
    from db.sql_connector import get_sql_connector
    Base.metadata.create_all(bind=get_sql_connector().engine)


if __name__ == '__main__':
    init_sql()
