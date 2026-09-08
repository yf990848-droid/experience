from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import requests
from elasticsearch import Elasticsearch
from fastapi import HTTPException

from constants import PRODUCT, FILTER, SOURCE, ID, DOC_ID, SCORE
from logger import logger
from memory_service.service_params import ProductInfo
from project_configs.settings import UNIFIED_INDEX, VECTOR_FIELD_MAP, \
    BM25_FIELD_MAP, EXCLUDED_SOURCE_FIELDS, SIMPLE_FILTER_FIELDS, GET_PDUNAME_URL, EXPERIENCE_PRODUCT_ID_FIELD
from db.es_connector import AI_test_es_client


def get_es_client() -> Elasticsearch:
    return AI_test_es_client


def _build_term_or_terms_clause(es_field: str, value: Union[str, List[str]]) -> Dict[str, Any]:
    """根据 value 类型构建 term 或 terms 子句：单值用 term，列表用 terms"""
    if isinstance(value, list):
        return {"terms": {es_field: value}}
    return {"term": {es_field: value}}


def _build_product_clauses(product: ProductInfo) -> List[Dict[str, Any]]:
    """从 ProductInfo 构建 product.* 的 term/terms 子句（值为列表时用 terms）"""
    return [
        _build_term_or_terms_clause(
            EXPERIENCE_PRODUCT_ID_FIELD if field == "product_id" else f"{PRODUCT}.{field}", value)
        for field, value in product.dict(exclude_none=True).items()
    ]


def _build_custom_filter_clauses(filter_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从自定义 filter dict 构建 term 子句，带 . 的字段直接使用，否则加 filter. 前缀"""
    return [
        {"term": {(field if "." in field else f"{FILTER}.{field}"): value}}
        for field, value in filter_dict.items()
        if value is not None
    ]


def build_filter_clauses(
        scene_id: Optional[Union[str, List[str]]] = None,
        product: Optional[ProductInfo] = None,
        filter_dict: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        doc_id: Optional[str] = None,
        scene: Optional[Union[str, List[str]]] = None,
        quality_only: bool = False,
) -> List[Dict[str, Any]]:
    """构建 ES bool filter 子句列表（声明式，低圈复杂度）。
    scene_id 和 scene 支持传入单个字符串或字符串列表，列表时使用 terms 查询。
    quality_only=True 时只返回质量检查通过的文档。
    """
    local_params = {"scene": scene, "scene_id": scene_id, "user_id": user_id}

    # 1. 简单 term/terms 字段
    clauses = [
        _build_term_or_terms_clause(SIMPLE_FILTER_FIELDS[key], value)
        for key, value in local_params.items()
        if value is not None
    ]

    # 2. doc_id 特殊映射到 _id
    if doc_id:
        clauses.append({"term": {"_id": doc_id}})

    # 3. product 子句
    if product:
        clauses.extend(_build_product_clauses(product))

    # 4. 自定义 filter 子句
    if filter_dict:
        clauses.extend(_build_custom_filter_clauses(filter_dict))

    if quality_only:
        clauses.append({"bool": {"must_not": [{"term": {"quality": False}}]}})

    return clauses


def format_hit(hit: dict) -> dict:
    source = hit.get(SOURCE, hit)
    result = {ID: hit.get(DOC_ID, hit.get("_id"))}
    result.update({k: v for k, v in source.items() if k not in EXCLUDED_SOURCE_FIELDS})
    return result


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    dot_val = float(np.dot(a, b))
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_val / (norm_a * norm_b)


def vector_absolute_normalize(cosine_score: float) -> float:
    return max(0.0, min(1.0, cosine_score))


def _safe_vector_score(doc_vector: Optional[List[float]], query_vector: List[float]) -> float:
    if doc_vector and len(doc_vector) == len(query_vector):
        return cosine_similarity(doc_vector, query_vector)
    return 0.0


def es_search(query_body: dict, error_msg: str) -> dict:
    try:
        es = get_es_client()
        return es.search(index=UNIFIED_INDEX, body=query_body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{error_msg}: {str(e)}")


def validate_search_field(search_field: str) -> None:
    if search_field not in VECTOR_FIELD_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的检索字段: {search_field}，可选: {list(VECTOR_FIELD_MAP.keys())}",
        )


def extract_hits_and_total(resp: dict) -> Tuple[List[dict], int]:
    """从 ES 响应中提取 hits 和 total，统一处理 total 的两种格式"""
    hits = resp.get("hits", {}).get("hits", [])
    total_raw = resp.get("hits", {}).get("total", 0)
    total = total_raw["value"] if isinstance(total_raw, dict) else total_raw
    return hits, int(total)


def bm25_search_with_fallback(
        query: str,
        filter_clauses: List[dict],
        candidate_size: int,
        search_field: str = "title",
) -> Tuple[List[dict], int, bool]:
    """BM25 检索，返回 (hits, total, is_fallback)"""
    es_field = BM25_FIELD_MAP.get(search_field, search_field)

    bm25_query = {
        "size": candidate_size,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [{"match": {es_field: {"query": query, "analyzer": "ik_smart"}}}],
                "filter": filter_clauses,
            }
        },
        "_source": True,
    }

    bm25_resp = es_search(bm25_query, "BM25 检索失败")
    bm25_hits, total = extract_hits_and_total(bm25_resp)

    if bm25_hits:
        return bm25_hits, total, False

    fallback_query = {
        "size": candidate_size,
        "track_total_hits": True,
        "query": {"bool": {"must": [{"match_all": {}}], "filter": filter_clauses}},
        "_source": True,
    }
    fallback_resp = es_search(fallback_query, "Fallback 检索失败")
    hits, total_fallback = extract_hits_and_total(fallback_resp)
    return hits, total_fallback, True


def bm25_min_max_normalize(candidates: List[dict]) -> None:
    if not candidates:
        return

    raw_scores = [c["bm25_raw"] for c in candidates]
    min_s, max_s = min(raw_scores), max(raw_scores)
    span = max_s - min_s

    for c in candidates:
        c["bm25_norm"] = (c["bm25_raw"] - min_s) / span if span > 0 else 0.0


def build_candidates(
        bm25_hits: List[dict],
        query_vector: List[float],
        search_field: str = "title",
) -> List[dict]:
    vector_field_key = VECTOR_FIELD_MAP.get(search_field)
    candidates: List[dict] = []
    for hit in bm25_hits:
        source = hit.get("_source", {})
        bm25_raw = hit.get("_score", 0.0) or 0.0
        vec_raw = _safe_vector_score(source.get(vector_field_key), query_vector) if vector_field_key else 0.0

        candidates.append({
            "hit": hit,
            "bm25_raw": bm25_raw,
            "vector_raw": vec_raw,
            "bm25_norm": 0.0,
            "vector_norm": vector_absolute_normalize(vec_raw),
        })
    return candidates


def fuse_and_rank(
        candidates: List[dict],
        w_vec: float,
        w_bm25: float,
        top_k: int,
        score_threshold: Optional[float] = None,
) -> List[dict]:
    for cand in candidates:
        cand["final_score"] = w_vec * cand["vector_norm"] + w_bm25 * cand["bm25_norm"]

    if score_threshold:
        candidates = [c for c in candidates if c["final_score"] >= score_threshold]

    candidates.sort(key=lambda x: x["final_score"], reverse=True)
    return candidates[:top_k]


def format_search_results(top_candidates: List[dict]) -> List[dict]:
    items = []
    for cand in top_candidates:
        item = format_hit(cand["hit"])
        item[SCORE] = {
            "final": round(cand["final_score"], 4),
            "vector_raw": round(cand["vector_raw"], 4),
            "vector_norm": round(cand["vector_norm"], 4),
            "bm25_raw": round(cand["bm25_raw"], 4),
            "bm25_norm": round(cand["bm25_norm"], 4),
        }
        items.append(item)
    return items


def paginate(items: List, page: int, page_size: int) -> dict:
    """通用分页工具，返回分页元数据和当前页数据"""
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    from_offset = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "items": items[from_offset: from_offset + page_size],
    }


def fetch_pdu_name_by_user_id(user_id: str) -> Optional[str]:
    if not user_id:
        return None

    try:
        url = GET_PDUNAME_URL + user_id
        resp = requests.get(url, timeout=5, verify=False)
        resp.raise_for_status()

        data = resp.json()[0]
        pdu_name = data.get("physicalDeliveryOfficeName")

        # 去掉结尾的 "(ICT BG)"
        if pdu_name and pdu_name.endswith("(ICT BG)"):
            pdu_name = pdu_name[:-len("(ICT BG)")].rstrip()

        return pdu_name

    except Exception as e:
        logger.info(f"获取 pdu_name 失败 (user_id={user_id}): {e}")
        return None


def get_all_scenes(mapper: dict) -> list:
    """提取所有需要查询的场景列表"""
    scenes = []
    for scene_map in mapper.values():
        for sub_scene, exp_list in scene_map.items():
            if exp_list:
                scenes.extend(exp_list)
            else:
                scenes.append(sub_scene)
    return scenes


def build_es_query(base_clauses: list, all_scenes: list) -> dict:
    """构建 ES 查询 Body"""
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": base_clauses or [{"match_all": {}}]
            }
        },
        "aggs": {
            "scene_counts": {
                "terms": {
                    "field": "scene",
                    "size": len(all_scenes) + 10,
                    "include": all_scenes,
                }
            }
        },
    }


def format_scene_result(mapper: dict, count_map: dict) -> dict:
    """将打平的 ES 聚合结果格式化为嵌套层级结构"""
    result = {}
    for stage, scene_map in mapper.items():
        stage_total = 0
        children = {}
        for sub_scene, exp_list in scene_map.items():
            if exp_list:
                # 1. 遍历一次构建 details，缓存 count_map 查询结果
                details = {exp: count_map.get(exp, 0) for exp in exp_list}
                # 2. 直接对缓存的值求和，避免二次遍历和二次查字典
                sub_total = sum(details.values())
            else:
                sub_total = count_map.get(sub_scene, 0)
                details = {}

            children[sub_scene] = {
                "total": sub_total,
                "details": details,
            }
            stage_total += sub_total

        result[stage] = {
            "total": stage_total,
            "children": children,
        }
    return result

