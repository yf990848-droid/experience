import io
import json
import uuid
import zipfile
from datetime import datetime
from typing import Any, Dict, Optional, List

import requests
from elasticsearch import NotFoundError
from fastapi import HTTPException, APIRouter, UploadFile, File, Form
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from api.rag import get_embedding
from constants import SUMMARY, SCENE, SCENE_ID, USER_ID, PRODUCT, DOC_ID, \
    VECTORS, TITLE_VECTOR, SUMMARY_VECTOR, EXPERIENCE_VECTOR, RAG_SEARCH_TEXT_VECTOR, SCORE, TITLE, \
    EXPERIENCE, RAG_SEARCH_TEXT, CREATED_AT, UPDATED_AT, METADATA, LOG, ACTION_OVERWRITTEN, ACTION_DELETED
from db_operate.sql_operator import SQLOperator
from exception.exceptions import ProjectException
from logger import logger
from memory_service.experience_manage import get_es_client, build_filter_clauses, es_search, extract_hits_and_total, \
    format_hit, validate_search_field, bm25_search_with_fallback, build_candidates, bm25_min_max_normalize, \
    fuse_and_rank, paginate, format_search_results, fetch_pdu_name_by_user_id, get_all_scenes, build_es_query, \
    format_scene_result
from memory_service.quality_checker import run_quality_check_and_update
from memory_service.service_params import DocumentCreate, DocumentUpdate, SearchByFilter, \
    SearchRequest, SearchWeights, ProductInfo, SceneCountRequest, UsageStatsRequest
from memory_service.usage_stats import get_experience_usage
from project_configs import settings
from project_configs.settings import UNIFIED_INDEX, MAX_HIT_CAP, OPTIONAL_VECTOR_FIELDS, UPDATE_PLAIN_FIELDS, \
    UPDATE_TEXT_FIELDS, CST, SKILL_DRAFTS_URL
from memory_service.version_manager import (
    archive_document, build_current_version_snapshot, list_versions_detail
)


def success_response(data: Any = None, msg: str = "success") -> dict:
    return {"code": 200, "msg": msg, "data": data}


def error_response(code: int, msg: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "msg": msg, "data": None},
    )


router_experience = APIRouter(prefix="/memory/experience")


def enrich_product_pdu_name(body: DocumentCreate) -> None:
    """
    根据 user_id 补全 product.pdu_name。
    """
    if not body.user_id:
        return

    pdu_name = fetch_pdu_name_by_user_id(body.user_id)
    if not pdu_name:
        return

    if body.product is None:
        body.product = ProductInfo(pdu_name=pdu_name)
        return

    if not body.product.pdu_name:
        body.product.pdu_name = pdu_name


def resolve_document_version_info(
        es,
        doc_id: str,
        has_input_doc_id: bool,
        now: str,
) -> Dict[str, Any]:
    """
    解析文档版本信息。

    - 如果用户传入 doc_id 且 ES 中存在该文档，则归档旧版本并生成新版本号
    - 如果不存在，则认为是新建
    - 如果用户未传 doc_id，则直接新建
    """
    default_version_info = {
        "existing_source": {},
        "is_overwrite": False,
        "archived_history_id": None,
        "new_version": 1,
        "created_at": now,
    }

    if not has_input_doc_id:
        return default_version_info

    try:
        existing = es.get(index=UNIFIED_INDEX, id=doc_id)
        existing_source = existing.get("_source", {})

        archived_history_id = archive_document(
            es_source=existing_source,
            doc_id=doc_id,
            action_type=ACTION_OVERWRITTEN,
        )

        return {
            "existing_source": existing_source,
            "is_overwrite": True,
            "archived_history_id": archived_history_id,
            "new_version": existing_source.get("version", 1) + 1,
            "created_at": existing_source.get(CREATED_AT, now),
        }

    except NotFoundError:
        return default_version_info


def build_unified_document(
        body: DocumentCreate,
        doc_id: str,
        now: str,
        created_at: str,
        version: int,
) -> Dict[str, Any]:
    """
    构造写入 ES 的统一文档结构。
    """
    return {
        SCENE_ID: body.scene_id,
        DOC_ID: doc_id,
        TITLE: body.title,
        TITLE_VECTOR: get_embedding(body.title),
        SUMMARY: body.summary,
        SUMMARY_VECTOR: get_embedding(body.summary),
        EXPERIENCE: body.experience,
        RAG_SEARCH_TEXT: body.rag_search_text,
        USER_ID: body.user_id,
        CREATED_AT: created_at,
        UPDATED_AT: now,
        PRODUCT: body.product.dict(exclude_none=True) if body.product else {},
        METADATA: body.metadata or {},
        LOG: body.log or {},
        SCENE: body.scene,
        "version": version,
        "quality": None,
        "quality_category": None,
        "quality_reason": "pending",
    }


def append_optional_vectors(
        doc: Dict[str, Any],
        body: DocumentCreate,
) -> List[str]:
    """
    处理可选向量字段，并返回已向量化字段列表。
    """
    vectorized_fields = ["title_vector", "summary_vector"]

    for attr_name, vector_const, vector_label in OPTIONAL_VECTOR_FIELDS:
        text_value = getattr(body, attr_name)

        if not text_value or not text_value.strip():
            continue

        doc[vector_const] = get_embedding(text_value)
        vectorized_fields.append(vector_label)

    return vectorized_fields


def index_unified_document(
        es,
        doc_id: str,
        doc: Dict[str, Any],
) -> str:
    """
    写入 ES，并返回 ES result 类型。
    """
    resp = es.index(index=UNIFIED_INDEX, id=doc_id, body=doc)
    return resp.get("result", "")


def add_quality_check_task(
        background_tasks: BackgroundTasks,
        doc_id: str,
        body: DocumentCreate,
) -> None:
    """
    添加后台质量检查任务。
    """
    check_content = "\n".join(filter(None, [
        body.title,
        body.summary,
        body.experience,
    ]))

    background_tasks.add_task(
        run_quality_check_and_update,
        doc_id,
        check_content,
    )


def upsert_experience(body: DocumentCreate, background_tasks=None):
    """API 和定时任务共用的写入函数；异常由调用方处理。"""
    es = get_es_client()
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    doc_id = body.doc_id or str(uuid.uuid4())

    enrich_product_pdu_name(body)

    version_info = resolve_document_version_info(
        es=es,
        doc_id=doc_id,
        has_input_doc_id=bool(body.doc_id),
        now=now,
    )

    doc = build_unified_document(
        body=body,
        doc_id=doc_id,
        now=now,
        created_at=version_info["created_at"],
        version=version_info["new_version"],
    )

    vectorized_fields = append_optional_vectors(
        doc=doc,
        body=body,
    )

    result_type = index_unified_document(
        es=es,
        doc_id=doc_id,
        doc=doc,
    )

    if background_tasks is not None:
        add_quality_check_task(background_tasks, doc_id, body)

    return {
        "id": doc_id,
        "scene_id": body.scene_id,
        "vectorized_fields": vectorized_fields,
        "version": version_info["new_version"],
        "is_overwrite": version_info["is_overwrite"],
        "archived_history_id": version_info["archived_history_id"],
        "upserted": int(result_type == "created"),
        "updated": int(result_type == "updated"),
    }
@router_experience.post("/doc")
def create_doc(body: DocumentCreate, background_tasks: BackgroundTasks):
    try:
        return success_response(data=upsert_experience(body, background_tasks))
    except Exception as e:
        return error_response(code=500, msg=f"写入失败: {str(e)}", status_code=500)


@router_experience.put("/doc/{doc_id}")
def update_doc(doc_id: str, body: DocumentUpdate, background_tasks: BackgroundTasks):
    es = get_es_client()

    try:
        existing = es.get(index=UNIFIED_INDEX, id=doc_id)
    except NotFoundError:
        return error_response(code=404, msg=f"文档 {doc_id} 不存在", status_code=404)

    update_fields: Dict[str, Any] = {}

    # 文本字段：更新文本 + 条件生成向量
    for attr_name, text_const, vector_const in UPDATE_TEXT_FIELDS:
        value = getattr(body, attr_name)
        if value is None:
            continue
        update_fields[text_const] = value
        if value.strip() and vector_const:
            update_fields[vector_const] = get_embedding(value)

    # 非文本字段：直接赋值或转换后赋值
    for attr_name, field_const, transform in UPDATE_PLAIN_FIELDS:
        value = getattr(body, attr_name)
        if value is None:
            continue
        update_fields[field_const] = transform(value) if transform else value

    if not update_fields:
        return error_response(code=400, msg="没有需要更新的字段", status_code=400)

    update_fields[UPDATED_AT] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # 如果更新了内容字段，重置 quality 并后台重新检查
    content_fields_updated = any(
        getattr(body, attr) is not None
        for attr in ["title", "summary", "experience"]
    )
    if content_fields_updated:
        # 先把 quality 置为 pending，等后台回填
        update_fields["quality"] = None
        update_fields["quality_category"] = None
        update_fields["quality_reason"] = "pending"

    try:
        resp = es.update(index=UNIFIED_INDEX, id=doc_id, body={"doc": update_fields})

        # 内容有变化时，后台重新做质量检查
        if content_fields_updated:
            existing_source = existing.get("_source", {})
            check_title = getattr(body, "title", None) or existing_source.get(TITLE, "")
            check_summary = getattr(body, "summary", None) or existing_source.get(SUMMARY, "")
            check_experience = getattr(body, "experience", None) or existing_source.get(EXPERIENCE, "")
            check_content = "\n".join(filter(None, [check_title, check_summary, check_experience]))
            background_tasks.add_task(run_quality_check_and_update, doc_id, check_content)

        return success_response(data={
            "id": doc_id,
            "updated": int(resp.get("result") == "updated"),
        })
    except Exception as e:
        return error_response(code=500, msg=f"更新失败: {str(e)}", status_code=500)


# ------------------ 删除接口 ------------------
def delete_experience(doc_id: str):
    """共用删除函数；不存在时抛 NotFoundError，由调用方决定处理方式。"""
    es = get_es_client()
    existing = es.get(index=UNIFIED_INDEX, id=doc_id)
    archive_document(es_source=existing.get("_source", {}), doc_id=doc_id,
                     action_type=ACTION_DELETED)
    es.delete(index=UNIFIED_INDEX, id=doc_id)
    return {"deleted": 1}


@router_experience.delete("/doc/{doc_id}")
def delete_doc(doc_id: str):
    try:
        return success_response(data=delete_experience(doc_id))
    except NotFoundError:
        return error_response(code=404, msg=f"文档 {doc_id} 不存在", status_code=404)
    except Exception as e:
        return error_response(code=500, msg=f"删除失败: {str(e)}", status_code=500)


def check_caller_id(caller_id):
    """缓冲期选填只告警，settings.CALLER_ID_REQUIRED=True 时缺失直接拦。"""
    cid = (caller_id or "").strip()
    if not cid:
        if settings.CALLER_ID_REQUIRED:
            return error_response(code=400, msg="caller_id(调用方工号)为必填字段", status_code=400)
        logger.warning("请求缺少 caller_id(调用方工号); 缓冲期内暂允许")
    return None  # None = 校验通过


# ------------------ 按条件检索（非向量） ------------------
@router_experience.post("/doc/search/by-filter")
def search_by_filter(req: SearchByFilter):
    clauses = build_filter_clauses(
        scene_id=req.scene_id,
        product=req.product,
        filter_dict=req.filter,
        user_id=req.user_id,
        doc_id=req.doc_id,
        scene=req.scene,
        quality_only=req.quality_only,
    )
    err = check_caller_id(req.caller_id)
    if err:
        return err

    from_offset = (req.page - 1) * req.page_size

    if from_offset + req.page_size > 10000:
        return error_response(
            code=400,
            msg="分页偏移量超出上限（page * page_size <= 10000），请缩小页码或使用更精确的过滤条件",
            status_code=400,
        )

    query_body = {
        "from": from_offset,
        "size": req.page_size,
        "query": {"bool": {"filter": clauses or [{"match_all": {}}]}},
        "_source": {"excludes": [VECTORS, TITLE_VECTOR, SUMMARY_VECTOR, EXPERIENCE_VECTOR, RAG_SEARCH_TEXT_VECTOR]},
    }
    if req.sort:
        query_body["sort"] = req.sort

    try:
        resp = es_search(query_body, "按条件检索失败")
    except HTTPException as e:
        return error_response(code=e.status_code, msg=e.detail, status_code=e.status_code)

    hits, total = extract_hits_and_total(resp)
    items = [format_hit(hit) for hit in hits]

    total_pages = (total + req.page_size - 1) // req.page_size
    return success_response(data={
        "total": total,
        "page": req.page,
        "page_size": req.page_size,
        "total_pages": total_pages,
        "has_next": req.page < total_pages,
        "has_prev": req.page > 1,
        "items": items,
    })


# ------------------ 混合检索（向量 + BM25） ------------------
@router_experience.post("/doc/search")
def search_docs(req: SearchRequest):
    """
    混合检索 —— 根据指定的 search_field 进行向量化打分与 BM25 检索，支持分页。
    search_field 可选: title, summary, experience, rag_search_text
    scene_id 和 scene 支持传入单个字符串或字符串列表，列表时使用 terms 查询匹配多个值。
    """
    err = check_caller_id(req.caller_id)
    if err:
        return err
    validate_search_field(req.search_field)

    weights = req.weights or SearchWeights()
    query_vector = get_embedding(req.query)

    filter_clauses = build_filter_clauses(
        scene_id=req.scene_id,
        product=req.product,
        filter_dict=req.filter,
        user_id=req.user_id,
        doc_id=req.doc_id,
        scene=req.scene,
        quality_only=req.quality_only,
    )

    try:
        bm25_hits, total_hits, is_fallback = bm25_search_with_fallback(
            req.query, filter_clauses,
            candidate_size=MAX_HIT_CAP,
            search_field=req.search_field,
        )
    except HTTPException as e:
        return error_response(code=e.status_code, msg=e.detail, status_code=e.status_code)

    candidates = build_candidates(bm25_hits, query_vector, search_field=req.search_field)

    if is_fallback:
        for c in candidates:
            c["bm25_raw"] = 0.0
            c["bm25_norm"] = 0.0
    else:
        bm25_min_max_normalize(candidates)

    ranked = fuse_and_rank(
        candidates, weights.vector, weights.bm25,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
    )

    page_info = paginate(ranked, req.page, req.page_size)
    items = format_search_results(page_info["items"])

    return success_response(data={
        "scene_id": req.scene_id,
        "search_field": req.search_field,
        "total_candidates": int(total_hits),
        "total_ranked": page_info["total"],
        "page": page_info["page"],
        "page_size": page_info["page_size"],
        "total_pages": page_info["total_pages"],
        "has_next": page_info["has_next"],
        "has_prev": page_info["has_prev"],
        "items": items,
    })


@router_experience.post("/doc/scene-count")
def get_scene_count(req: SceneCountRequest):
    # 0. 场景树以调用方传入为准;
    scene_mapper = req.scene_mapper
    if not scene_mapper:
        return error_response(code=400, msg="scene_mapper 不能为空", status_code=400)

    # 1. 准备查询数据
    all_scenes = get_all_scenes(scene_mapper)
    if not all_scenes:
        # 没有叶子场景, 直接按空树返回, 避免构造无效 ES 查询
        return success_response(data=format_scene_result(scene_mapper, {}))

    base_clauses = build_filter_clauses(
        scene_id=req.scene_id,
        product=req.product,
        user_id=req.user_id,
        quality_only=False,
    )
    query_body = build_es_query(base_clauses, all_scenes)

    # 2. 执行 ES 查询
    try:
        resp = es_search(query_body, "场景计数查询失败")
    except HTTPException as e:
        return error_response(code=e.status_code, msg=e.detail, status_code=e.status_code)

    # 3. 解析结果并返回(用同一棵传入的树回填计数)
    buckets = resp.get("aggregations", {}).get("scene_counts", {}).get("buckets", [])
    count_map = {b["key"]: b["doc_count"] for b in buckets}

    result = format_scene_result(scene_mapper, count_map)
    return success_response(data=result)


@router_experience.get("/doc/{doc_id}/history/detail")
def list_doc_versions_detail(doc_id: str, page: int = 1, page_size: int = 20):
    """
    获取某个 doc 的所有版本完整内容(包含当前版本 + 全部历史版本)。
    items 按版本号倒序排列,当前版本(is_current=true)排在最前。
    """
    es = get_es_client()
    current_snapshot: Optional[Dict[str, Any]] = None
    current_version: Optional[int] = None
    doc_exists_in_es = False

    try:
        existing = es.get(index=UNIFIED_INDEX, id=doc_id)
    except NotFoundError:
        # 文档已删除,只返回历史
        existing = None

    if existing is not None:
        current_source = existing.get("_source", {})
        current_version = current_source.get("version", 1)
        current_snapshot = build_current_version_snapshot(current_source, doc_id)
        doc_exists_in_es = True

    # 获取历史版本(分页)
    history_data = list_versions_detail(doc_id, page=page, page_size=page_size)

    # 当前版本只在第 1 页插入,且不占用 page_size 配额
    items = history_data["items"]
    if current_snapshot is not None and page == 1:
        items = [current_snapshot] + items

    # 给历史快照也补一个 is_current 标记,方便前端统一处理
    for item in items:
        if "is_current" not in item:
            item["is_current"] = False

    history_data["items"] = items
    history_data["doc_id"] = doc_id
    history_data["current_version"] = current_version
    history_data["doc_exists_in_es"] = doc_exists_in_es

    return success_response(data=history_data)


@router_experience.post("/stats/usage")
def experience_usage_stats(req: UsageStatsRequest):
    if req.end_time <= req.start_time:
        return error_response(code=400, msg="end_time 必须大于 start_time", status_code=400)
    try:
        data = get_experience_usage(
            start_time=req.start_time,
            end_time=req.end_time,
            only_success=req.only_success,
        )
    except Exception as e:
        return error_response(code=500, msg=f"统计失败: {str(e)}", status_code=500)
    return success_response(data=data)


def _json_field(value):
    """dict/list -> JSON 字符串;字符串原样;None 返回 None。"""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _forward_to_skill_drafts(record: dict, data: bytes, summary) -> requests.Response:
    """转发给下游 /api/skill-drafts（multipart/form-data）。"""
    files = {
        "file": (record["archive_name"] or "skill.zip", data, "application/zip"),
    }
    form = {
        "userId": record["employee_id"],
        "skillName": record["skill_name"],
        "description": record["description"],
        "sessionId": record["session_id"],
        "sessionCreateTime": record["first_trace_time"],
        "skillGenerateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ide": record["ide_type"],
        "codeRepo": record["remote_git_repo_path"],
        "firstMessage": record["first_input"],
        "source": record.get("source", "gui"),
    }
    # requests 的 data 不接受 None，统一兜底成空串
    form = {k: ("" if v is None else v) for k, v in form.items()}

    resp = requests.post(SKILL_DRAFTS_URL, files=files, data=form, timeout=300, verify=False)
    resp.raise_for_status()
    return resp


@router_experience.post("/skill/upload")
def upload_skill(
        archive: UploadFile = File(..., description="skill 目录打包的 zip"),
        skill_name: str = Form(...),
        description: str = Form(...),
        employee_id: str = Form(...),
        session_id: str = Form(...),
):
    data = archive.file.read()
    if not data:
        return error_response(code=400, msg="压缩包为空", status_code=400)

    if not zipfile.is_zipfile(io.BytesIO(data)):
        return error_response(code=400, msg="archive 不是合法的 zip", status_code=400)

    # 用 session_id 回查 summary 表，带出 ide / 第一个 input / 代码仓
    summary = SQLOperator().get_session_summary(session_id)
    if not summary:
        return error_response(
            code=404,
            msg=f"session_id 错误，未找到 session_id 对应的会话信息: {session_id}",
            status_code=404,
        )

    first_input = summary.first_input
    ide_type = summary.ide_type
    remote_git_repo_path = summary.remote_git_repo_path
    first_trace_time = summary.first_trace_time

    record = {
        "skill_id": str(uuid.uuid4()),
        "skill_name": skill_name,
        "description": description,
        "employee_id": employee_id,
        "session_id": session_id,
        "first_input": first_input,
        "ide_type": ide_type,
        "remote_git_repo_path": remote_git_repo_path,
        "archive_name": archive.filename,
        "archive_data": data,
        "archive_size": len(data),
        "first_trace_time": first_trace_time,
        "source": "gui",  # 数据来源，暂固定 gui
    }

    try:
        SQLOperator().upsert_skill(record)
    except ProjectException as e:
        return error_response(code=500, msg=f"skill 落库失败: {e}", status_code=500)

    # 落库成功后，转发给下游 /api/skill-drafts
    try:
        _forward_to_skill_drafts(record, data, summary)
    except requests.RequestException as e:
        return error_response(code=502, msg=f"转发 skill-drafts 失败: {e}", status_code=502)

    return success_response(
        data={
            "skill_id": record["skill_id"],
            "archive_size": len(data),
        }
    )
