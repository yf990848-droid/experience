import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

import memory_service.version_manager as svc
from constants import ACTION_OVERWRITTEN, ACTION_DELETED, ACTION_ROLLBACK


class FakeHistoryRecord:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.doc_id = kwargs.get("doc_id", "doc-1")
        self.version = kwargs.get("version", 1)
        self.title = kwargs.get("title")
        self.summary = kwargs.get("summary")
        self.experience = kwargs.get("experience")
        self.rag_search_text = kwargs.get("rag_search_text")
        self.scene_id = kwargs.get("scene_id")
        self.scene = kwargs.get("scene")
        self.user_id = kwargs.get("user_id")
        self.quality = kwargs.get("quality")
        self.quality_category = kwargs.get("quality_category")
        self.quality_reason = kwargs.get("quality_reason")
        self.product = kwargs.get("product")
        self.metadata_json = kwargs.get("metadata_json")
        self.log = kwargs.get("log")
        self.action_type = kwargs.get("action_type")
        self.snapshot_created_at = kwargs.get("snapshot_created_at")
        self.snapshot_updated_at = kwargs.get("snapshot_updated_at")
        self.archived_at = kwargs.get("archived_at")


class FakeQuery:
    def __init__(self, records=None, count_value=None):
        self.records = records or []
        self.count_value = count_value if count_value is not None else len(self.records)
        self.offset_value = None
        self.limit_value = None

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def count(self):
        return self.count_value

    def all(self):
        records = self.records
        if self.offset_value is not None:
            records = records[self.offset_value:]
        if self.limit_value is not None:
            records = records[:self.limit_value]
        return records

    def first(self):
        return self.records[0] if self.records else None


class TestExperienceVersionService(unittest.TestCase):

    def make_client(self):
        client = MagicMock()
        client.add = MagicMock()
        client.commit = MagicMock()
        client.refresh = MagicMock()
        client.rollback = MagicMock()
        client.close = MagicMock()
        client.query = MagicMock()
        return client

    def patch_sql_connector(self, client):
        connector = SimpleNamespace(client=client)
        return patch.object(svc, "get_sql_connector", return_value=connector)

    def test_parse_dt_none(self):
        self.assertIsNone(svc._parse_dt(None))
        self.assertIsNone(svc._parse_dt(""))

    def test_parse_dt_datetime(self):
        dt = datetime(2024, 1, 1, 12, 30, 0)
        self.assertEqual(svc._parse_dt(dt), dt)

    def test_parse_dt_valid_string(self):
        result = svc._parse_dt("2024-01-01 12:30:00")
        self.assertEqual(result, datetime(2024, 1, 1, 12, 30, 0))

    def test_parse_dt_invalid_string(self):
        self.assertIsNone(svc._parse_dt("invalid-date"))

    def test_to_json_text_none(self):
        self.assertIsNone(svc._to_json_text(None))

    def test_to_json_text_string(self):
        self.assertEqual(svc._to_json_text("hello"), "hello")

    def test_to_json_text_dict(self):
        data = {"name": "测试", "age": 18}
        self.assertEqual(
            svc._to_json_text(data),
            json.dumps(data, ensure_ascii=False)
        )

    def test_to_json_text_unserializable(self):
        data = {"bad": object()}
        self.assertIsNone(svc._to_json_text(data))

    def test_load_json_none(self):
        self.assertIsNone(svc._load_json(None))
        self.assertIsNone(svc._load_json(""))

    def test_load_json_valid(self):
        self.assertEqual(svc._load_json('{"a": 1}'), {"a": 1})

    def test_load_json_invalid_returns_original_text(self):
        self.assertEqual(svc._load_json("not-json"), "not-json")

    def test_archive_document_empty_source(self):
        with patch.object(svc.logger, "warning") as mock_warning:
            result = svc.archive_document({}, "doc-1", ACTION_DELETED)

        self.assertIsNone(result)
        mock_warning.assert_called_once()

    def test_archive_document_success(self):
        client = self.make_client()

        def refresh_side_effect(record):
            record.id = 123

        client.refresh.side_effect = refresh_side_effect

        es_source = {
            "version": 2,
            svc.TITLE: "标题",
            svc.SUMMARY: "摘要",
            svc.EXPERIENCE: "经验内容",
            svc.RAG_SEARCH_TEXT: "搜索文本",
            svc.SCENE_ID: "scene-1",
            svc.SCENE: "场景",
            svc.USER_ID: "user-1",
            "quality": 90,
            "quality_category": "high",
            "quality_reason": "good",
            svc.PRODUCT: {"id": "p1"},
            svc.METADATA: {"k": "v"},
            svc.LOG: [{"op": "create"}],
            svc.CREATED_AT: "2024-01-01 10:00:00",
            svc.UPDATED_AT: "2024-01-02 10:00:00",
        }

        with self.patch_sql_connector(client), \
                patch.object(svc, "ExperienceVersionHistory", side_effect=FakeHistoryRecord), \
                patch.object(svc.logger, "info") as mock_info:
            result = svc.archive_document(
                es_source,
                "doc-1",
                ACTION_OVERWRITTEN
            )

        self.assertEqual(result, 123)
        client.add.assert_called_once()
        client.commit.assert_called_once()
        client.refresh.assert_called_once()
        client.close.assert_called_once()
        mock_info.assert_called_once()

        record = client.add.call_args.args[0]

        self.assertEqual(record.doc_id, "doc-1")
        self.assertEqual(record.version, 2)
        self.assertEqual(record.title, "标题")
        self.assertEqual(record.summary, "摘要")
        self.assertEqual(record.experience, "经验内容")
        self.assertEqual(record.product, json.dumps({"id": "p1"}, ensure_ascii=False))
        self.assertEqual(record.metadata_json, json.dumps({"k": "v"}, ensure_ascii=False))
        self.assertEqual(record.log, json.dumps([{"op": "create"}], ensure_ascii=False))
        self.assertEqual(record.action_type, ACTION_OVERWRITTEN)
        self.assertEqual(record.snapshot_created_at, datetime(2024, 1, 1, 10, 0, 0))
        self.assertEqual(record.snapshot_updated_at, datetime(2024, 1, 2, 10, 0, 0))

    def test_archive_document_default_version(self):
        client = self.make_client()

        def refresh_side_effect(record):
            record.id = 1

        client.refresh.side_effect = refresh_side_effect

        es_source = {
            svc.TITLE: "无 version 文档",
        }

        with self.patch_sql_connector(client), \
                patch.object(svc, "ExperienceVersionHistory", side_effect=FakeHistoryRecord):
            result = svc.archive_document(
                es_source,
                "doc-1",
                ACTION_DELETED
            )

        self.assertEqual(result, 1)

        record = client.add.call_args.args[0]
        self.assertEqual(record.version, 1)

    def test_archive_document_sqlalchemy_error(self):
        client = self.make_client()
        client.commit.side_effect = SQLAlchemyError("db error")

        es_source = {
            "version": 1,
            svc.TITLE: "标题",
        }

        with self.patch_sql_connector(client), \
                patch.object(svc, "ExperienceVersionHistory", side_effect=FakeHistoryRecord), \
                patch.object(svc.logger, "error") as mock_error:
            result = svc.archive_document(
                es_source,
                "doc-1",
                ACTION_DELETED
            )

        self.assertIsNone(result)
        client.rollback.assert_called_once()
        client.close.assert_called_once()
        mock_error.assert_called_once()

    def test_history_record_to_dict(self):
        record = FakeHistoryRecord(
            id=10,
            doc_id="doc-1",
            version=5,
            title="标题",
            summary="摘要",
            experience="经验",
            rag_search_text="搜索",
            scene_id="scene-1",
            scene="场景",
            user_id="user-1",
            quality=80,
            quality_category="medium",
            quality_reason="ok",
            product='{"id": "p1"}',
            metadata_json='{"source": "test"}',
            log='[{"action": "update"}]',
            action_type=ACTION_ROLLBACK,
            snapshot_created_at=datetime(2024, 1, 1, 10, 0, 0),
            snapshot_updated_at=datetime(2024, 1, 2, 10, 0, 0),
            archived_at=datetime(2024, 1, 3, 10, 0, 0),
        )

        result = svc._history_record_to_dict(record)

        self.assertEqual(result["id"], 10)
        self.assertEqual(result["doc_id"], "doc-1")
        self.assertEqual(result["version"], 5)
        self.assertEqual(result["title"], "标题")
        self.assertEqual(result["product"], {"id": "p1"})
        self.assertEqual(result["metadata"], {"source": "test"})
        self.assertEqual(result["log"], [{"action": "update"}])
        self.assertEqual(result["action_type"], ACTION_ROLLBACK)
        self.assertEqual(result["snapshot_created_at"], "2024-01-01 10:00:00")
        self.assertEqual(result["snapshot_updated_at"], "2024-01-02 10:00:00")
        self.assertEqual(result["archived_at"], "2024-01-03 10:00:00")

    def test_build_current_version_snapshot(self):
        es_source = {
            "version": 7,
            svc.TITLE: "当前标题",
            svc.SUMMARY: "当前摘要",
            svc.EXPERIENCE: "当前经验",
            svc.RAG_SEARCH_TEXT: "当前搜索文本",
            svc.SCENE_ID: "scene-1",
            svc.SCENE: "场景",
            svc.USER_ID: "user-1",
            "quality": 100,
            "quality_category": "high",
            "quality_reason": "excellent",
            svc.PRODUCT: {"id": "p1"},
            svc.METADATA: {"source": "es"},
            svc.LOG: [{"action": "update"}],
            "change_note": "修改说明",
            "updated_by": "admin",
            svc.CREATED_AT: "2024-01-01 10:00:00",
            svc.UPDATED_AT: "2024-01-02 10:00:00",
        }

        result = svc.build_current_version_snapshot(es_source, "doc-1")

        self.assertIsNone(result["id"])
        self.assertEqual(result["doc_id"], "doc-1")
        self.assertEqual(result["version"], 7)
        self.assertEqual(result["title"], "当前标题")
        self.assertEqual(result["summary"], "当前摘要")
        self.assertEqual(result["action_type"], "current")
        self.assertEqual(result["change_note"], "修改说明")
        self.assertEqual(result["updated_by"], "admin")
        self.assertIsNone(result["archived_at"])
        self.assertTrue(result["is_current"])

    def test_build_current_version_snapshot_default_version(self):
        es_source = {
            svc.TITLE: "标题",
        }

        result = svc.build_current_version_snapshot(es_source, "doc-1")

        self.assertEqual(result["version"], 1)
        self.assertEqual(result["title"], "标题")
        self.assertEqual(result["action_type"], "current")
        self.assertTrue(result["is_current"])

    def test_list_versions_detail(self):
        client = self.make_client()

        records = [
            FakeHistoryRecord(
                id=1,
                doc_id="doc-1",
                version=2,
                title="标题2",
                product='{"id": "p2"}',
                metadata_json='{"m": 2}',
                log='[{"a": 2}]',
                action_type=ACTION_DELETED,
                archived_at=datetime(2024, 1, 2, 10, 0, 0),
            ),
            FakeHistoryRecord(
                id=2,
                doc_id="doc-1",
                version=1,
                title="标题1",
                product='{"id": "p1"}',
                metadata_json='{"m": 1}',
                log='[{"a": 1}]',
                action_type=ACTION_OVERWRITTEN,
                archived_at=datetime(2024, 1, 1, 10, 0, 0),
            ),
        ]

        client.query.return_value = FakeQuery(records=records, count_value=2)

        with self.patch_sql_connector(client):
            result = svc.list_versions_detail("doc-1", page=1, page_size=20)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["total_pages"], 1)
        self.assertEqual(len(result["items"]), 2)

        self.assertEqual(result["items"][0]["id"], 1)
        self.assertEqual(result["items"][0]["doc_id"], "doc-1")
        self.assertEqual(result["items"][0]["version"], 2)
        self.assertEqual(result["items"][0]["title"], "标题2")
        self.assertEqual(result["items"][0]["product"], {"id": "p2"})
        self.assertEqual(result["items"][0]["metadata"], {"m": 2})
        self.assertEqual(result["items"][0]["log"], [{"a": 2}])

        client.close.assert_called_once()

    def test_list_versions_detail_pagination(self):
        client = self.make_client()

        records = [
            FakeHistoryRecord(id=1, version=3),
            FakeHistoryRecord(id=2, version=2),
            FakeHistoryRecord(id=3, version=1),
        ]

        client.query.return_value = FakeQuery(records=records, count_value=45)

        with self.patch_sql_connector(client):
            result = svc.list_versions_detail("doc-1", page=2, page_size=20)

        self.assertEqual(result["total"], 45)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["page_size"], 20)
        self.assertEqual(result["total_pages"], 3)
        self.assertTrue(result["has_next"])
        self.assertTrue(result["has_prev"])

        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
