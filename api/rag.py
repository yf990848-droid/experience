import json
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import requests
from elasticsearch import NotFoundError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.es_connector import AI_test_es_client
from logger import logger
from project_configs.settings import EMBEDDING_MODELS, DEFAULT_EMBEDDING_MODEL, \
    EXCLUDE_FIELDS, INDEX_NAME, SEARCH_FIELD_CONFIG, BM25_CANDIDATE_MULTIPLIER

router_test_case_steps = APIRouter(prefix="/memory")
CST = ZoneInfo("Asia/Shanghai")


class StepListRequest(BaseModel):
    """分页查询请求体"""
    page: int = 1  # 当前页码，从 1 开始
    page_size: int = 20  # 每页条数，默认 20
    sort_field: str = "created_at"  # 排序字段
    sort_order: str = "desc"  # 排序方向: asc / desc
    # 可选过滤条件
    case_id: Optional[str] = None
    case_name: Optional[str] = None
    product_line_name: Optional[str] = None
    pdu_name: Optional[str] = None
    product_id: Optional[str] = None
    version_name: Optional[str] = None
    feature: Optional[str] = None
    tool_type: Optional[str] = None
    tool_content_type: Optional[str] = None  # 脚本类型
    detailed_step_description: Optional[str] = None
    param: Optional[str] = None


class StepCreate(BaseModel):
    """写入请求体"""
    case_id: str
    case_name: str
    step_order: int
    total_steps: Optional[int] = None
    step_description: str
    checkpoint: Optional[str] = None
    detailed_checkpoint: Optional[str] = None
    tool_type: Optional[str] = None
    tool_name: Optional[str] = None
    tool_content: Optional[str] = None
    tool_content_type: Optional[str] = None
    product_line_name: Optional[str] = None
    pdu_name: Optional[str] = None
    product_id: Optional[str] = None
    version_name: Optional[str] = None
    feature: Optional[str] = None
    detailed_step_description: Optional[str] = None
    param: Optional[str] = None


class StepUpdate(BaseModel):
    """更新请求体"""
    case_id: Optional[str] = None
    case_name: Optional[str] = None
    step_order: Optional[int] = None
    total_steps: Optional[int] = None
    step_description: Optional[str] = None
    checkpoint: Optional[str] = None
    detailed_checkpoint: Optional[str] = None
    tool_type: Optional[str] = None
    tool_name: Optional[str] = None
    tool_content: Optional[str] = None
    tool_content_type: Optional[str] = None
    product_line_name: Optional[str] = None
    pdu_name: Optional[str] = None
    product_id: Optional[str] = None
    version_name: Optional[str] = None
    feature: Optional[str] = None
    detailed_step_description: Optional[str] = None
    param: Optional[str] = None


class DeleteByCaseId(BaseModel):
    """按用例 ID 删除请求体"""
    case_id: str


class SearchByCaseId(BaseModel):
    """按用例 ID 检索请求体"""
    scene: Optional[str] = None
    case_id: str
    product_line_name: Optional[str] = None
    pdu_name: Optional[str] = None
    product_id: Optional[str] = None
    version_name: Optional[str] = None
    feature: Optional[str] = None
    tool_type: Optional[str] = None


class SearchWeights(BaseModel):
    """混合检索权重"""
    vector: float = 0.7
    bm25: float = 0.3


class StepSearch(BaseModel):
    scene: Optional[str] = None
    query: str
    search_field: str = "step_description"
    top_k: int = 10
    weights: SearchWeights = SearchWeights()
    product_line_name: Optional[str] = None
    pdu_name: Optional[str] = None
    product_id: Optional[str] = None
    version_name: Optional[str] = None
    feature: Optional[str] = None
    tool_type: Optional[str] = None


def get_embedding(text: str, model_type: str = DEFAULT_EMBEDDING_MODEL) -> List[float]:
    """调用 embedding 模型获取向量"""
    if model_type not in EMBEDDING_MODELS:
        raise ValueError(f"不支持的模型类型: {model_type}，可选: {list(EMBEDDING_MODELS.keys())}")

    url = EMBEDDING_MODELS[model_type]["url"]
    data_init = {
        "prompt": "null",
        "batch_input": json.dumps([text]),
    }
    data = {"data": json.dumps(data_init)}

    try:
        resp = requests.post(url=url, json=data, verify=False, timeout=30)
        resp.raise_for_status()
        data_first = json.loads(resp.text[5:])["content"]
        resp_data = json.loads(data_first)
        vector = resp_data[text]
        return vector
    except Exception as e:
        logger.error(f"Embedding 服务调用失败: {e}")
        raise HTTPException(status_code=502, detail=f"Embedding 服务调用失败: {str(e)}")


def build_filter_clauses(
        product_line_name: Optional[str] = None,
        pdu_name: Optional[str] = None,
        product_id: Optional[str] = None,
        version_name: Optional[str] = None,
        feature: Optional[str] = None,
        tool_type: Optional[str] = None,
) -> List[dict]:
    """构建可选过滤条件"""
    filter_map = {
        "product_line_name": product_line_name,
        "pdu_name": pdu_name,
        "product_id": product_id,
        "version_name": version_name,
        "feature": feature,
        "tool_type": tool_type,
    }
    return [{"term": {field: value}} for field, value in filter_map.items() if value is not None]


def build_filter_clauses_from_req(req) -> List[dict]:
    """从请求对象中提取过滤条件"""
    return build_filter_clauses(
        product_line_name=getattr(req, "product_line_name", None),
        pdu_name=getattr(req, "pdu_name", None),
        product_id=getattr(req, "product_id", None),
        version_name=getattr(req, "version_name", None),
        feature=getattr(req, "feature", None),
        tool_type=getattr(req, "tool_type", None),
    )


def _validate_list_params(req: StepListRequest):
    """校验分页查询参数，不合法则抛出 HTTPException"""
    if req.page < 1:
        raise HTTPException(status_code=400, detail="page 必须 >= 1")
    if req.page_size < 1 or req.page_size > 500:
        raise HTTPException(status_code=400, detail="page_size 必须在 1~500 之间")
    if req.sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_order 只能为 asc 或 desc")

    from_offset = (req.page - 1) * req.page_size
    if from_offset + req.page_size > 10000:
        raise HTTPException(
            status_code=400,
            detail="分页偏移量超出上限（page * page_size <= 10000），请缩小页码或使用更精确的过滤条件",
        )


def _build_list_bool_query(req: StepListRequest) -> dict:
    """
    为 /list 接口构建完整的 ES bool 查询。
    核心过滤字段：
      - case_id (用例编号): 精确匹配 (term)
      - case_name (用例名称): 模糊匹配 (match + ik_smart)
      - tool_type (工具类型): 精确匹配 (term)
      - tool_content_type (脚本类型): 精确匹配 (term)
    以及其余通用 term 过滤字段。
    """
    must_clauses = []

    # 所有精确匹配字段统一用 term（放 filter，不评分）
    term_fields = {
        "case_name": req.case_name,
        "case_id": req.case_id,
        "tool_type": req.tool_type,
        "tool_content_type": req.tool_content_type,
        "product_line_name": req.product_line_name,
        "pdu_name": req.pdu_name,
        "product_id": req.product_id,
        "version_name": req.version_name,
        "feature": req.feature,
    }
    filter_clauses = [
        {"term": {field: value}}
        for field, value in term_fields.items()
        if value is not None
    ]

    if not must_clauses and not filter_clauses:
        return {"match_all": {}}

    bool_body = {"must": must_clauses or [{"match_all": {}}]}
    if filter_clauses:
        bool_body["filter"] = filter_clauses
    return {"bool": bool_body}


def _build_list_query_body(req: StepListRequest) -> dict:
    """组装完整的 ES 分页查询体"""
    from_offset = (req.page - 1) * req.page_size
    return {
        "from": from_offset,
        "size": req.page_size,
        "query": _build_list_bool_query(req),
        "sort": [
            {req.sort_field: {"order": req.sort_order}},
            {"_id": {"order": "asc"}},
        ],
        "_source": {"excludes": EXCLUDE_FIELDS},
        "track_total_hits": True,
    }


def _parse_list_response(resp: dict, req: StepListRequest) -> dict:
    """将 ES 响应解析为分页结果"""
    hits = resp["hits"]["hits"]
    total_raw = resp["hits"]["total"]
    total = total_raw["value"] if isinstance(total_raw, dict) else total_raw
    items = [format_hit(hit) for hit in hits]
    total_pages = (total + req.page_size - 1) // req.page_size

    return {
        "ok": True,
        "total": total,
        "page": req.page,
        "page_size": req.page_size,
        "total_pages": total_pages,
        "has_next": req.page < total_pages,
        "has_prev": req.page > 1,
        "items": items,
    }


def format_hit(hit: dict) -> dict:
    """格式化 ES 返回的 hit，排除向量字段"""
    source = hit["_source"]
    result = {"id": hit["_id"]}
    for key, value in source.items():
        if key not in EXCLUDE_FIELDS:
            result[key] = value
    return result


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算余弦相似度"""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def min_max_normalize(scores: List[float]) -> List[float]:
    """Min-Max 归一化到 [0, 1]"""
    if not scores:
        return []
    min_s = min(scores)
    max_s = max(scores)
    if max_s == min_s:
        return [1.0] * len(scores)
    return [(s - min_s) / (max_s - min_s) for s in scores]


def _safe_vector_score(doc_vector: Optional[List[float]], query_vector: List[float]) -> float:
    """安全计算单条文档的向量相似度"""
    if doc_vector and len(doc_vector) == len(query_vector):
        return cosine_similarity(query_vector, doc_vector)
    return 0.0


def _build_candidates(
        bm25_hits: List[dict],
        query_vector: List[float],
        vector_field: str = "step_vector",
) -> List[dict]:
    candidates = []
    for hit in bm25_hits:
        source = hit["_source"]
        bm25_score = hit.get("_score", 0.0) or 0.0
        vec_score = _safe_vector_score(source.get(vector_field), query_vector)
        candidates.append({
            "hit": hit,
            "bm25_raw": bm25_score,
            "vector_raw": vec_score,
        })
    return candidates


def _fuse_and_rank(candidates: List[dict], w_vec: float, w_bm25: float, top_k: int) -> List[dict]:
    """对候选列表做归一化、加权融合、排序并截取 top_k"""
    bm25_normalized = min_max_normalize([c["bm25_raw"] for c in candidates])
    vector_normalized = min_max_normalize([c["vector_raw"] for c in candidates])

    for i, cand in enumerate(candidates):
        cand["bm25_norm"] = bm25_normalized[i]
        cand["vector_norm"] = vector_normalized[i]
        cand["final_score"] = w_vec * vector_normalized[i] + w_bm25 * bm25_normalized[i]

    candidates.sort(key=lambda x: x["final_score"], reverse=True)
    return candidates[:top_k]


def _format_search_results(top_candidates: List[dict]) -> List[dict]:
    """将排序后的候选格式化为接口返回结构"""
    items = []
    for cand in top_candidates:
        item = format_hit(cand["hit"])
        item["score"] = {
            "final": round(cand["final_score"], 4),
            "vector": round(cand["vector_raw"], 4),
            "bm25": round(cand["bm25_raw"], 4),
        }
        items.append(item)
    return items


def _es_search(query_body: dict, error_msg: str) -> dict:
    """封装 ES search 调用，统一异常处理"""
    try:
        return AI_test_es_client.search(index=INDEX_NAME, body=query_body)
    except Exception as e:
        logger.error(f"{error_msg}: {e}")
        raise HTTPException(status_code=500, detail=f"{error_msg}: {str(e)}")


def _bm25_search_with_fallback(
        query: str,
        filter_clauses: List[dict],
        candidate_size: int,
        text_field: str = "step_description",
) -> List[dict]:
    bm25_query = {
        "size": candidate_size,
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            text_field: {
                                "query": query,
                                "analyzer": "ik_smart",
                            }
                        }
                    }
                ],
                "filter": filter_clauses,
            }
        },
        "_source": True,
    }

    bm25_resp = _es_search(bm25_query, "BM25 检索失败")
    bm25_hits = bm25_resp["hits"]["hits"]

    if bm25_hits:
        return bm25_hits

    # BM25 无结果，退化为全量扫描（按过滤条件筛选）
    fallback_query = {
        "size": candidate_size,
        "query": {
            "bool": {
                "must": [{"match_all": {}}],
                "filter": filter_clauses,
            }
        },
        "_source": True,
    }
    fallback_resp = _es_search(fallback_query, "Fallback 检索失败")
    return fallback_resp["hits"]["hits"]


def _resolve_search_fields(search_field: str) -> tuple:
    vector_field = SEARCH_FIELD_CONFIG.get(search_field)
    if vector_field is None:
        allowed = list(SEARCH_FIELD_CONFIG.keys())
        raise HTTPException(
            status_code=400,
            detail=f"search_field 不合法: '{search_field}'，可选值: {allowed}",
        )
    return search_field, vector_field


def _prepare_single_step_upsert_docs(step: StepCreate, now: str) -> tuple:
    """
    构造 update/upsert 所需文档：
    - update_doc: 只更新传入字段，未传字段不覆盖
    - upsert_doc: 文档不存在时创建
    """
    doc_id = f"{step.case_id}_step_{step.step_order}"

    # 只保留请求里实际传入的字段；未传的不进 doc
    raw_doc = step.dict(exclude_unset=True)

    # step_description 是必填，正常都会有
    if "step_description" in raw_doc:
        raw_doc["step_vector"] = get_embedding(raw_doc["step_description"])

    # checkpoint：只有本次请求传了，才处理 checkpoint_vector
    if "checkpoint" in raw_doc:
        raw_doc["checkpoint_vector"] = (
            get_embedding(raw_doc["checkpoint"]) if raw_doc["checkpoint"] else None
        )

    # detailed_step_description：只有本次请求传了，才处理向量
    if "detailed_step_description" in raw_doc:
        raw_doc["detailed_step_description_vector"] = (
            get_embedding(raw_doc["detailed_step_description"])
            if raw_doc["detailed_step_description"] else None
        )

    update_doc = dict(raw_doc)
    update_doc["updated_at"] = now

    upsert_doc = dict(raw_doc)
    upsert_doc["created_at"] = now
    upsert_doc["updated_at"] = now

    return doc_id, update_doc, upsert_doc


def _try_prepare_step(i: int, step: StepCreate, now: str, actions: list, errors: list):
    """尝试准备单条步骤，失败则记录到 errors"""
    try:
        doc_id, update_doc, upsert_doc = _prepare_single_step_upsert_docs(step, now)
        actions.append({"update": {"_index": INDEX_NAME, "_id": doc_id}})
        actions.append({
            "doc": update_doc,
            "upsert": upsert_doc,
        })
    except Exception as e:
        errors.append({
            "index": i,
            "case_id": step.case_id,
            "step_order": step.step_order,
            "error": str(e),
        })


@router_test_case_steps.get("/health")
def health_check():
    """健康检查"""
    try:
        info = AI_test_es_client.info()
        return {"ok": True, "es_version": info["version"]["number"]}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ES 连接失败: {str(e)}")


@router_test_case_steps.post("/test-case-steps")
def create_step(step: StepCreate):
    """写入/更新单条用例步骤：有则更新，无则创建；未传字段保留旧值"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    doc_id, update_doc, upsert_doc = _prepare_single_step_upsert_docs(step, now)

    try:
        resp = AI_test_es_client.update(
            index=INDEX_NAME,
            id=doc_id,
            body={
                "doc": update_doc,
                "upsert": upsert_doc,
            },
            refresh="wait_for",
        )
        result_type = resp.get("result", "")
        return {
            "ok": True,
            "id": doc_id,
            "upserted": 1 if result_type == "created" else 0,
            "updated": 1 if result_type == "updated" else 0,
        }
    except Exception as e:
        logger.error(f"写入失败: {e}")
        raise HTTPException(status_code=500, detail=f"写入失败: {str(e)}")


@router_test_case_steps.post("/test-case-steps/bulk")
def bulk_create_steps(steps: List[StepCreate]):
    """批量写入用例步骤"""
    if not steps:
        raise HTTPException(status_code=400, detail="步骤列表不能为空")

    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    actions = []
    errors = []

    for i, step in enumerate(steps):
        _try_prepare_step(i, step, now, actions, errors)

    if not actions:
        return {"ok": False, "message": "所有步骤向量生成失败", "errors": errors}

    # 执行 bulk
    body_lines = ""
    for item in actions:
        body_lines += json.dumps(item, ensure_ascii=False) + "\n"

    try:
        resp = AI_test_es_client.bulk(body=body_lines, refresh="wait_for")
        succeeded = sum(1 for item in resp["items"] if item["update"]["status"] in (200, 201))
        failed = sum(1 for item in resp["items"] if item["update"]["status"] not in (200, 201))
        return {
            "ok": True,
            "total": len(steps),
            "succeeded": succeeded,
            "failed": failed + len(errors),
            "errors": errors if errors else None,
        }
    except Exception as e:
        logger.error(f"批量写入失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量写入失败: {str(e)}")


@router_test_case_steps.put("/test-case-steps/{doc_id}")
def update_step(doc_id: str, step: StepUpdate):
    """更新单条用例步骤"""
    # 过滤掉 None 值，只更新传入的字段
    update_fields = {k: v for k, v in step.dict().items() if v is not None}

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    # 如果 step_description 有变更，重新生成 step_vector
    if "step_description" in update_fields:
        update_fields["step_vector"] = get_embedding(update_fields["step_description"])

    # 如果 checkpoint 有变更，重新生成 checkpoint_vector
    if "checkpoint" in update_fields:
        update_fields["checkpoint_vector"] = get_embedding(update_fields["checkpoint"])

    if "detailed_step_description" in update_fields:
        update_fields["detailed_step_description_vector"] = get_embedding(
            update_fields["detailed_step_description"]
        )
    update_fields["updated_at"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    try:
        resp = AI_test_es_client.update(
            index=INDEX_NAME,
            id=doc_id,
            body={"doc": update_fields},
        )
        return {
            "ok": True,
            "id": doc_id,
            "upserted": 0,
            "updated": 1 if resp.get("result") == "updated" else 0,
        }
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    except Exception as e:
        logger.error(f"更新失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router_test_case_steps.delete("/test-case-steps/{doc_id}")
def delete_step(doc_id: str):
    """按步骤 ID 删除单条步骤"""
    try:
        AI_test_es_client.delete(index=INDEX_NAME, id=doc_id)
        return {"ok": True, "deleted": 1}
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    except Exception as e:
        logger.error(f"删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router_test_case_steps.post("/test-case-steps/delete-by-case")
def delete_by_case_id(req: DeleteByCaseId):
    """按用例 ID 删除该用例下所有步骤"""
    try:
        resp = AI_test_es_client.delete_by_query(
            index=INDEX_NAME,
            body={
                "query": {
                    "term": {"case_id": req.case_id}
                }
            },
            refresh=True,
        )
        deleted_count = resp.get("deleted", 0)
        return {"ok": True, "deleted": deleted_count}
    except Exception as e:
        logger.error(f"按用例删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router_test_case_steps.post("/test-case-steps/search/by-case-id")
def search_by_case_id(req: SearchByCaseId):
    """按用例 ID 精确检索，返回该用例下所有步骤（按 step_order 排序）"""
    filter_clauses = build_filter_clauses_from_req(req)

    query_body = {
        "size": 10000,
        "query": {
            "bool": {
                "must": [{"term": {"case_id": req.case_id}}],
                "filter": filter_clauses,
            }
        },
        "sort": [{"step_order": {"order": "asc"}}],
        "_source": {"excludes": EXCLUDE_FIELDS},
    }

    resp = _es_search(query_body, "用例检索失败")
    hits = resp["hits"]["hits"]
    items = [format_hit(hit) for hit in hits]
    return {
        "ok": True,
        "total": len(items),
        "items": items,
    }


@router_test_case_steps.post("/test-case-steps/search")
def search_steps(req: StepSearch):
    # 1. 解析检索字段
    text_field, vector_field = _resolve_search_fields(req.search_field)

    # 2. 生成查询向量
    query_vector = get_embedding(req.query)

    # 3. BM25 检索（含 fallback）
    filter_clauses = build_filter_clauses_from_req(req)
    candidate_size = req.top_k * BM25_CANDIDATE_MULTIPLIER
    bm25_hits = _bm25_search_with_fallback(
        req.query, filter_clauses, candidate_size, text_field=text_field
    )

    # 4. 构建候选 & 计算向量相似度
    candidates = _build_candidates(bm25_hits, query_vector, vector_field=vector_field)

    # 5. 归一化 + 加权融合 + 排序
    top_candidates = _fuse_and_rank(candidates, req.weights.vector, req.weights.bm25, req.top_k)

    # 6. 格式化结果
    items = _format_search_results(top_candidates)

    return {
        "ok": True,
        "search_field": req.search_field,
        "top_k": req.top_k,
        "items": items,
    }


@router_test_case_steps.post("/test-case-steps/list")
def list_steps(req: StepListRequest):
    """
    分页查询所有用例步骤，支持可选过滤与排序。
    核心过滤字段：
      - case_id (用例编号): 精确匹配
      - case_name (用例名称): 模糊匹配（ik_smart 分词）
      - tool_type (工具类型): 精确匹配
      - tool_content_type (脚本类型): 精确匹配
    """
    _validate_list_params(req)
    query_body = _build_list_query_body(req)
    resp = _es_search(query_body, "分页查询失败")
    return _parse_list_response(resp, req)
