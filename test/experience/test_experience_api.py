import unittest
from unittest.mock import patch, MagicMock
from sqlalchemy.dialects import registry as _sa_registry

from fastapi.testclient import TestClient
from fastapi import FastAPI
from elasticsearch import NotFoundError

FAKE_VECTOR = [0.1] * 768

with patch("api.rag.get_embedding", return_value=FAKE_VECTOR):
    from api.experience_api import router_experience, success_response, error_response

app = FastAPI()
app.include_router(router_experience)
client = TestClient(app)
_sa_registry.load("postgresql.gaussdb")
BASE_URL = "/memory/experience"

MINIMAL_CREATE_BODY = {
    "scene_id": "scene_001",
    "title": "测试标题",
    "summary": "测试摘要",
    "experience": "测试经验",
    "rag_search_text": "测试检索文本",
    "user_id": "c00872275",
    "scene": "default",
}

MINIMAL_UPDATE_BODY = {
    "title": "新标题",
}

SEARCH_FILTER_BODY = {
    "scene_id": "scene_001",
    "page": 1,
    "page_size": 10,
}

SEARCH_BODY = {
    "query": "测试查询",
    "scene_id": "scene_001",
    "search_field": "title",
    "page": 1,
    "page_size": 10,
}


def _es_index_response(result="created"):
    return {"result": result, "_id": "fake_id"}


def _es_update_response(result="updated"):
    return {"result": result}


def _es_get_response(doc_id="doc_001"):
    return {"_id": doc_id, "_source": {"title": "old"}}


def _es_search_response(hits=None, total=1):
    if hits is None:
        hits = [{
            "_id": "doc_001",
            "_score": 1.0,
            "_source": {
                "scene_id": "scene_001",
                "doc_id": "doc_001",
                "title": "测试",
                "summary": "摘要",
                "experience": "经验",
                "rag_search_text": "检索",
                "user_id": "user_001",
                "created_at": "2025-01-01 00:00:00",
                "updated_at": "2025-01-01 00:00:00",
                "product": {},
                "metadata": {},
                "log": {},
                "scene": "default",
            },
        }]
    return {
        "hits": {
            "total": {"value": total},
            "hits": hits,
        }
    }


class TestCreateDoc(unittest.TestCase):

    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.get_es_client")
    def test_create_doc_success(self, mock_get_es, mock_embed):
        mock_es = MagicMock()
        mock_es.index.return_value = _es_index_response("created")
        mock_get_es.return_value = mock_es

        resp = client.post(f"{BASE_URL}/doc", json=MINIMAL_CREATE_BODY)
        data = resp.json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["code"], 200)
        self.assertEqual(data["data"]["upserted"], 1)
        self.assertEqual(data["data"]["updated"], 0)
        self.assertIn("vectorized_fields", data["data"])
        mock_es.index.assert_called_once()

    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.get_es_client")
    def test_create_doc_with_custom_doc_id(self, mock_get_es, mock_embed):
        mock_es = MagicMock()
        mock_es.index.return_value = _es_index_response("created")
        mock_get_es.return_value = mock_es

        body = {**MINIMAL_CREATE_BODY, "doc_id": "my_custom_id"}
        resp = client.post(f"{BASE_URL}/doc", json=body)
        data = resp.json()

        self.assertEqual(data["data"]["id"], "my_custom_id")

    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.get_es_client")
    def test_create_doc_upsert_updated(self, mock_get_es, mock_embed):
        """doc_id 已存在时 ES 返回 result=updated"""
        mock_es = MagicMock()
        mock_es.index.return_value = _es_index_response("updated")
        mock_get_es.return_value = mock_es

        resp = client.post(f"{BASE_URL}/doc", json=MINIMAL_CREATE_BODY)
        data = resp.json()

        self.assertEqual(data["data"]["upserted"], 0)
        self.assertEqual(data["data"]["updated"], 1)

    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.get_es_client")
    def test_create_doc_es_exception(self, mock_get_es, mock_embed):
        mock_es = MagicMock()
        mock_es.index.side_effect = Exception("connection refused")
        mock_get_es.return_value = mock_es

        resp = client.post(f"{BASE_URL}/doc", json=MINIMAL_CREATE_BODY)
        data = resp.json()

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(data["code"], 500)
        self.assertIn("写入失败", data["msg"])


class TestUpdateDoc(unittest.TestCase):

    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.get_es_client")
    def test_update_doc_success(self, mock_get_es, mock_embed):
        mock_es = MagicMock()
        mock_es.get.return_value = _es_get_response("doc_001")
        mock_es.update.return_value = _es_update_response("updated")
        mock_get_es.return_value = mock_es

        resp = client.put(f"{BASE_URL}/doc/doc_001", json=MINIMAL_UPDATE_BODY)
        data = resp.json()

        self.assertEqual(data["code"], 200)
        self.assertEqual(data["data"]["updated"], 1)
        mock_es.update.assert_called_once()

    @patch("api.experience_api.get_es_client")
    def test_update_doc_not_found(self, mock_get_es):
        mock_es = MagicMock()
        mock_es.get.side_effect = NotFoundError(404, "not found", {})
        mock_get_es.return_value = mock_es

        resp = client.put(f"{BASE_URL}/doc/nonexistent", json=MINIMAL_UPDATE_BODY)
        data = resp.json()

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(data["code"], 404)
        self.assertIn("不存在", data["msg"])

    @patch("api.experience_api.get_es_client")
    def test_update_doc_no_fields(self, mock_get_es):
        mock_es = MagicMock()
        mock_es.get.return_value = _es_get_response("doc_001")
        mock_get_es.return_value = mock_es

        resp = client.put(f"{BASE_URL}/doc/doc_001", json={})
        data = resp.json()

        self.assertEqual(data["code"], 400)
        self.assertIn("没有需要更新的字段", data["msg"])

    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.get_es_client")
    def test_update_doc_es_exception(self, mock_get_es, mock_embed):
        mock_es = MagicMock()
        mock_es.get.return_value = _es_get_response("doc_001")
        mock_es.update.side_effect = Exception("write error")
        mock_get_es.return_value = mock_es

        resp = client.put(f"{BASE_URL}/doc/doc_001", json=MINIMAL_UPDATE_BODY)
        data = resp.json()

        self.assertEqual(resp.status_code, 500)
        self.assertIn("更新失败", data["msg"])


class TestDeleteDoc(unittest.TestCase):

    @patch("api.experience_api.archive_document", return_value=1)
    @patch("api.experience_api.get_es_client")
    def test_delete_doc_success(self, mock_get_es, mock_archive):
        mock_es = MagicMock()
        mock_es.get.return_value = {"_source": {"version": 1}}
        mock_es.delete.return_value = {"result": "deleted"}
        mock_get_es.return_value = mock_es

        resp = client.delete(f"{BASE_URL}/doc/doc_001")
        data = resp.json()

        self.assertEqual(data["code"], 200)
        self.assertEqual(data["data"]["deleted"], 1)

    @patch("api.experience_api.archive_document", return_value=None)
    @patch("api.experience_api.get_es_client")
    def test_delete_doc_not_found(self, mock_get_es, mock_archive):
        mock_es = MagicMock()
        mock_es.get.side_effect = NotFoundError(404, "not found", {})
        mock_get_es.return_value = mock_es

        resp = client.delete(f"{BASE_URL}/doc/nonexistent")
        data = resp.json()

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(data["code"], 404)

    @patch("api.experience_api.get_es_client")
    def test_delete_doc_es_exception(self, mock_get_es):
        mock_es = MagicMock()
        mock_es.delete.side_effect = Exception("cluster down")
        mock_get_es.return_value = mock_es

        resp = client.delete(f"{BASE_URL}/doc/doc_001")
        data = resp.json()

        self.assertEqual(resp.status_code, 500)
        self.assertIn("删除失败", data["msg"])


class TestSearchByFilter(unittest.TestCase):

    @patch("api.experience_api.es_search")
    @patch("api.experience_api.build_filter_clauses", return_value=[])
    def test_search_by_filter_success(self, mock_build, mock_es_search):
        mock_es_search.return_value = _es_search_response(total=1)

        resp = client.post(f"{BASE_URL}/doc/search/by-filter", json=SEARCH_FILTER_BODY)
        data = resp.json()

        self.assertEqual(data["code"], 200)
        self.assertEqual(data["data"]["total"], 1)
        self.assertEqual(data["data"]["page"], 1)
        self.assertIsInstance(data["data"]["items"], list)
        self.assertIn("has_next", data["data"])
        self.assertIn("has_prev", data["data"])

    def test_search_by_filter_offset_exceeds_limit(self):
        body = {**SEARCH_FILTER_BODY, "page": 1001, "page_size": 10}
        resp = client.post(f"{BASE_URL}/doc/search/by-filter", json=body)
        data = resp.json()

        self.assertEqual(data["code"], 400)
        self.assertIn("分页偏移量超出上限", data["msg"])

    @patch("api.experience_api.es_search")
    @patch("api.experience_api.build_filter_clauses", return_value=[])
    def test_search_by_filter_empty_results(self, mock_build, mock_es_search):
        mock_es_search.return_value = _es_search_response(hits=[], total=0)

        resp = client.post(f"{BASE_URL}/doc/search/by-filter", json=SEARCH_FILTER_BODY)
        data = resp.json()

        self.assertEqual(data["data"]["total"], 0)
        self.assertEqual(data["data"]["items"], [])
        self.assertFalse(data["data"]["has_next"])
        self.assertFalse(data["data"]["has_prev"])

    @patch("api.experience_api.es_search")
    @patch("api.experience_api.build_filter_clauses", return_value=[])
    def test_search_by_filter_pagination(self, mock_build, mock_es_search):
        hits = [
            {"_id": f"doc_{i}", "_score": 1.0, "_source": {"title": f"t{i}"}}
            for i in range(5)
        ]
        mock_es_search.return_value = _es_search_response(hits=hits, total=25)

        body = {**SEARCH_FILTER_BODY, "page": 2, "page_size": 5}
        resp = client.post(f"{BASE_URL}/doc/search/by-filter", json=body)
        data = resp.json()

        self.assertEqual(data["data"]["total"], 25)
        self.assertEqual(data["data"]["total_pages"], 5)
        self.assertTrue(data["data"]["has_next"])
        self.assertTrue(data["data"]["has_prev"])


class TestSearchDocs(unittest.TestCase):

    @patch("api.experience_api.format_search_results")
    @patch("api.experience_api.paginate")
    @patch("api.experience_api.fuse_and_rank")
    @patch("api.experience_api.bm25_min_max_normalize")
    @patch("api.experience_api.build_candidates")
    @patch("api.experience_api.bm25_search_with_fallback")
    @patch("api.experience_api.build_filter_clauses", return_value=[])
    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.validate_search_field")
    def test_search_docs_success(
            self, mock_validate, mock_embed, mock_filter,
            mock_bm25, mock_candidates, mock_normalize,
            mock_fuse, mock_paginate, mock_format,
    ):
        mock_bm25.return_value = (
            [{"_id": "doc_001", "_score": 1.5, "_source": {"title": "t"}}],
            1,
            False,
        )
        mock_candidates.return_value = [
            {"doc_id": "doc_001", "bm25_raw": 1.5, "vec_score": 0.9}
        ]
        mock_fuse.return_value = [
            {"doc_id": "doc_001", "final_score": 0.85}
        ]
        mock_paginate.return_value = {
            "items": [{"doc_id": "doc_001", "final_score": 0.85}],
            "total": 1, "page": 1, "page_size": 10,
            "total_pages": 1, "has_next": False, "has_prev": False,
        }
        mock_format.return_value = [{"doc_id": "doc_001", "score": 0.85}]

        resp = client.post(f"{BASE_URL}/doc/search", json=SEARCH_BODY)
        data = resp.json()

        self.assertEqual(data["code"], 200)
        self.assertEqual(data["data"]["total_candidates"], 1)
        self.assertIsInstance(data["data"]["items"], list)
        mock_validate.assert_called_once_with("title")
        mock_normalize.assert_called_once()

    @patch("api.experience_api.format_search_results")
    @patch("api.experience_api.paginate")
    @patch("api.experience_api.fuse_and_rank")
    @patch("api.experience_api.bm25_min_max_normalize")
    @patch("api.experience_api.build_candidates")
    @patch("api.experience_api.bm25_search_with_fallback")
    @patch("api.experience_api.build_filter_clauses", return_value=[])
    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.validate_search_field")
    def test_search_docs_fallback_zeroes_bm25(
            self, mock_validate, mock_embed, mock_filter,
            mock_bm25, mock_candidates, mock_normalize,
            mock_fuse, mock_paginate, mock_format,
    ):
        """当 bm25 走 fallback 时，候选的 bm25 分数应被置零"""
        candidate = {"doc_id": "doc_001", "bm25_raw": 1.5, "vec_score": 0.9}
        mock_bm25.return_value = ([], 0, True)  # is_fallback=True
        mock_candidates.return_value = [candidate]
        mock_fuse.return_value = [candidate]
        mock_paginate.return_value = {
            "items": [candidate], "total": 1, "page": 1,
            "page_size": 10, "total_pages": 1,
            "has_next": False, "has_prev": False,
        }
        mock_format.return_value = [candidate]

        resp = client.post(f"{BASE_URL}/doc/search", json=SEARCH_BODY)

        # fallback 模式下不应调用 normalize，而是直接置零
        mock_normalize.assert_not_called()
        self.assertEqual(candidate["bm25_raw"], 0.0)
        self.assertEqual(candidate["bm25_norm"], 0.0)

    @patch("api.experience_api.format_search_results")
    @patch("api.experience_api.paginate")
    @patch("api.experience_api.fuse_and_rank")
    @patch("api.experience_api.bm25_min_max_normalize")
    @patch("api.experience_api.build_candidates")
    @patch("api.experience_api.bm25_search_with_fallback")
    @patch("api.experience_api.build_filter_clauses", return_value=[])
    @patch("api.experience_api.get_embedding", return_value=FAKE_VECTOR)
    @patch("api.experience_api.validate_search_field")
    def test_search_docs_with_custom_weights(
            self, mock_validate, mock_embed, mock_filter,
            mock_bm25, mock_candidates, mock_normalize,
            mock_fuse, mock_paginate, mock_format,
    ):
        mock_bm25.return_value = ([], 1, False)
        mock_candidates.return_value = []
        mock_fuse.return_value = []
        mock_paginate.return_value = {
            "items": [], "total": 0, "page": 1,
            "page_size": 10, "total_pages": 0,
            "has_next": False, "has_prev": False,
        }
        mock_format.return_value = []

        body = {**SEARCH_BODY, "weights": {"vector": 0.8, "bm25": 0.2}}
        resp = client.post(f"{BASE_URL}/doc/search", json=body)

        # 验证自定义权重被传入 fuse_and_rank
        call_args = mock_fuse.call_args
        self.assertAlmostEqual(call_args[0][1], 0.8)  # vector weight
        self.assertAlmostEqual(call_args[0][2], 0.2)  # bm25 weight


class TestHelpers(unittest.TestCase):

    def test_success_response_default(self):
        result = success_response()
        self.assertEqual(result["code"], 200)
        self.assertEqual(result["msg"], "success")
        self.assertIsNone(result["data"])

    def test_success_response_with_data(self):
        result = success_response(data={"key": "value"}, msg="ok")
        self.assertEqual(result["data"], {"key": "value"})
        self.assertEqual(result["msg"], "ok")

    def test_error_response(self):
        resp = error_response(code=404, msg="not found", status_code=404)
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
