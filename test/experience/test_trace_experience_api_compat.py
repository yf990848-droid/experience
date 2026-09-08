"""加载真实 API 路由，隔离内网依赖，验证共用函数的响应及归档行为。"""
import ast
import importlib.util
import json
import sys
import types
from datetime import timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from elasticsearch import NotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def api(monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'api' / 'experience_api.py'
    tree = ast.parse(path.read_text())
    # 只替代外部连接和未上传的公共模块，保留真实请求模型、路由及业务函数。
    modules = ('api.rag', 'constants', 'db_operate.sql_operator', 'exception.exceptions',
               'logger', 'memory_service.experience_manage', 'memory_service.quality_checker',
               'memory_service.usage_stats', 'project_configs.settings', 'memory_service.version_manager')
    for name in modules:
        fake = types.ModuleType(name)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == name:
                for entry in node.names:
                    setattr(fake, entry.name, entry.name.lower() if name == 'constants' else Mock())
        monkeypatch.setitem(sys.modules, name, fake)
    settings = sys.modules['project_configs.settings']
    settings.CST = timezone.utc
    settings.UNIFIED_INDEX = 'test_index'
    settings.OPTIONAL_VECTOR_FIELDS = [('experience', 'experience_vector', 'experience_vector')]
    settings.UPDATE_PLAIN_FIELDS = []
    settings.UPDATE_TEXT_FIELDS = [('title', 'title', 'title_vector')]
    import project_configs
    monkeypatch.setattr(project_configs, 'settings', settings, raising=False)
    spec = importlib.util.spec_from_file_location('trace_api_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.fetch_pdu_name_by_user_id.return_value = None
    module.get_embedding.return_value = [0.1] * 384
    app = FastAPI()
    app.include_router(module.router_experience)
    return module, TestClient(app)


def body():
    return dict(doc_id='tracefix_test', scene_id='421', user_id='0', title='失败现象',
                summary='有效修复', experience='修复记录', product={'product_id': '1058'})


def test_api_create_preserves_response_and_quality(api):
    module, client = api
    es = module.get_es_client.return_value
    es.get.side_effect = NotFoundError(404, 'missing', {})
    es.index.return_value = {'result': 'created'}
    response = client.post('/memory/experience/doc', json=body())
    assert response.status_code == 200
    assert response.json()['data']['upserted'] == 1
    assert response.json()['data']['version'] == 1
    assert es.index.call_args.kwargs['body']['product']['product_id'] == '1058'
    module.run_quality_check_and_update.assert_called_once()


def test_task_common_write_archives_and_does_not_schedule_api_background(api):
    module, client = api
    es = module.get_es_client.return_value
    es.get.return_value = {'_source': {'version': 2, 'created_at': 'old'}}
    es.index.return_value = {'result': 'updated'}
    module.archive_document.return_value = 'archive1'
    response = module.upsert_experience(module.DocumentCreate(**body()))
    assert response['version'] == 3 and response['is_overwrite'] is True
    assert es.index.call_args.kwargs['body']['created_at'] == 'old'
    module.archive_document.assert_called_once()
    module.run_quality_check_and_update.assert_not_called()


def test_api_delete_archives_and_preserves_not_found(api):
    module, client = api
    es = module.get_es_client.return_value
    es.get.return_value = {'_source': {'title': 'old'}}
    assert client.delete('/memory/experience/doc/example').json()['data'] == {'deleted': 1}
    module.archive_document.assert_called_once()
    es.get.side_effect = NotFoundError(404, 'missing', {})
    assert client.delete('/memory/experience/doc/missing').status_code == 404
    with pytest.raises(NotFoundError):
        module.delete_experience('missing')


def test_common_write_propagates_failure_api_returns_500(api):
    module, client = api
    es = module.get_es_client.return_value
    es.get.side_effect = NotFoundError(404, 'missing', {})
    es.index.side_effect = RuntimeError('failed')
    with pytest.raises(RuntimeError):
        module.upsert_experience(module.DocumentCreate(**body()))
    assert client.post('/memory/experience/doc', json=body()).status_code == 500
