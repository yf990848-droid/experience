import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import desc

from db.sql_connector import get_sql_connector
from db_operate.sql_models import ExperienceVersionHistory
from logger import logger
from constants import (
    TITLE, SUMMARY, EXPERIENCE, RAG_SEARCH_TEXT,
    SCENE_ID, SCENE, USER_ID, PRODUCT, METADATA, LOG,
    CREATED_AT, UPDATED_AT,
)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _to_json_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _load_json(text: Optional[str]) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def archive_document(
        es_source: Dict[str, Any],
        doc_id: str,
        action_type: str,
) -> Optional[int]:
    """
    把 ES 中的一份文档快照写入历史表。
    归档失败只记日志,不抛异常,避免阻断主流程。
    返回归档后的 history.id。
    """
    if not es_source:
        logger.warning(f"archive_document: 空的 es_source, doc_id={doc_id}, 跳过")
        return None

    current_version = es_source.get("version", 1)

    try:
        client = get_sql_connector().client
    except Exception as e:
        logger.error(f"archive_document: 获取数据库连接失败, doc_id={doc_id}, err={e}")
        return None

    try:
        record = ExperienceVersionHistory(
            doc_id=doc_id,
            version=current_version,
            title=es_source.get(TITLE),
            summary=es_source.get(SUMMARY),
            experience=es_source.get(EXPERIENCE),
            rag_search_text=es_source.get(RAG_SEARCH_TEXT),
            scene_id=es_source.get(SCENE_ID),
            scene=es_source.get(SCENE),
            user_id=es_source.get(USER_ID),
            quality=es_source.get("quality"),
            quality_category=es_source.get("quality_category"),
            quality_reason=es_source.get("quality_reason"),
            product=_to_json_text(es_source.get(PRODUCT)),
            metadata_json=_to_json_text(es_source.get(METADATA)),
            log=_to_json_text(es_source.get(LOG)),
            action_type=action_type,
            snapshot_created_at=_parse_dt(es_source.get(CREATED_AT)),
            snapshot_updated_at=_parse_dt(es_source.get(UPDATED_AT)),
            archived_at=datetime.now(),
        )
        client.add(record)
        client.commit()
        client.refresh(record)
        logger.info(
            f"archive_document: doc_id={doc_id}, version={current_version}, "
            f"action={action_type}, history_id={record.id}"
        )
        return record.id
    except SQLAlchemyError as e:
        client.rollback()
        logger.error(f"archive_document 失败: doc_id={doc_id}, err={e}")
        return None
    finally:
        client.close()


def _history_record_to_dict(r: ExperienceVersionHistory) -> Dict[str, Any]:
    return {
        "id": r.id,
        "doc_id": r.doc_id,
        "version": r.version,
        "title": r.title,
        "summary": r.summary,
        "experience": r.experience,
        "rag_search_text": r.rag_search_text,
        "scene_id": r.scene_id,
        "scene": r.scene,
        "user_id": r.user_id,
        "quality": r.quality,
        "quality_category": r.quality_category,
        "quality_reason": r.quality_reason,
        "product": _load_json(r.product),
        "metadata": _load_json(r.metadata_json),
        "log": _load_json(r.log),
        "action_type": r.action_type,
        "snapshot_created_at": r.snapshot_created_at.strftime("%Y-%m-%d %H:%M:%S")
        if r.snapshot_created_at else None,
        "snapshot_updated_at": r.snapshot_updated_at.strftime("%Y-%m-%d %H:%M:%S")
        if r.snapshot_updated_at else None,
        "archived_at": r.archived_at.strftime("%Y-%m-%d %H:%M:%S")
        if r.archived_at else None,
    }


def build_current_version_snapshot(es_source: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    """把 ES 主文档转成和历史快照同样格式的字典,标记为 current"""
    return {
        "id": None,  # 不是历史表的记录,没有数据库 id
        "doc_id": doc_id,
        "version": es_source.get("version", 1),
        "title": es_source.get(TITLE),
        "summary": es_source.get(SUMMARY),
        "experience": es_source.get(EXPERIENCE),
        "rag_search_text": es_source.get(RAG_SEARCH_TEXT),
        "scene_id": es_source.get(SCENE_ID),
        "scene": es_source.get(SCENE),
        "user_id": es_source.get(USER_ID),
        "quality": es_source.get("quality"),
        "quality_category": es_source.get("quality_category"),
        "quality_reason": es_source.get("quality_reason"),
        "product": es_source.get(PRODUCT),
        "metadata": es_source.get(METADATA),
        "log": es_source.get(LOG),
        "action_type": "current",  # 关键标记:区分于 overwritten/deleted/rollback
        "change_note": es_source.get("change_note"),
        "updated_by": es_source.get("updated_by"),
        "snapshot_created_at": es_source.get(CREATED_AT),
        "snapshot_updated_at": es_source.get(UPDATED_AT),
        "archived_at": None,  # 当前版本未归档
        "is_current": True,
    }


def list_versions_detail(doc_id: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """查询某个 doc 的全部历史版本(分页,按版本号倒序),带完整内容"""
    client = get_sql_connector().client
    try:
        q = client.query(ExperienceVersionHistory).filter(
            ExperienceVersionHistory.doc_id == doc_id
        )
        total = q.count()
        records = (
            q.order_by(desc(ExperienceVersionHistory.version),
                       desc(ExperienceVersionHistory.archived_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [_history_record_to_dict(r) for r in records]
        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "items": items,
        }
    finally:
        client.close()
