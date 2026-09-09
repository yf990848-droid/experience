"""本任务离线测试：真实 SQL 事务 + 模拟数据接口、模型和 ES。"""
import copy
import json
from unittest.mock import Mock

import pytest
import requests
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError

from db_operate.trace_experience_store import TraceStateStore
from memory_service.trace_experience_pipeline import (
    Pipeline, StepClient, Extractor, build_body, doc_id, identity, normalize,
    parse_model_array, utc_time,
)


def config():
    return dict(job_name='test', range_start='2026-08-01 00:00:00',
                range_end='2026-10-01 00:00:00', page_size=10,
                source_url='https://example.invalid', extraction_version='v1',
                model_name='test', context_limit=100000, max_output_tokens=1000,
                safety_margin=100, max_pages_per_run=5, retry_trace_limit=100)


def step(id=1, **kwargs):
    data = dict(id=id, caseId='case', testUser='no user', groupId=1058,
                updateTime='2026-09-02 10:25:08', startTime=id, endTime=id + 1,
                fixResult='success', executeResult=None,
                diffContent={'hasChanged': True, 'changedLines': ['-bad()', '+good()'],
                             'failLogic': 'MML', 'failDetail': '22952'}, customStruct=[])
    data.update(kwargs)
    return data


def item(id='1', **kwargs):
    data = dict(fix_step_id=id, valid=True, reason='修改与失败直接相关',
                related_step_ids=[id], title='MML 配置失败', failure_phenomenon='MML 配置失败',
                summary='参数修正后修复有效', debug_trace='修改参数，修复有效',
                error_log='22952', diff='修改参数', root_cause='参数错误',
                pattern='[触发场景] 错误参数 → [修复动作] 修正参数', rag_search_text='MML 22952')
    data.update(kwargs)
    return data


class FakeWriter:
    def __init__(self):
        self.docs, self.puts, self.deletes, self.qualities = {}, [], [], []
        self.fail_put = False

    def get(self, id):
        return copy.deepcopy(self.docs.get(id))

    def put(self, body):
        if self.fail_put:
            raise RuntimeError('write failed')
        self.docs[body['doc_id']] = copy.deepcopy(body)
        self.puts.append(body['doc_id'])

    def delete(self, id):
        self.docs.pop(id, None)
        self.deletes.append(id)

    def quality(self, body):
        self.qualities.append(body['doc_id'])


@pytest.fixture
def setup():
    cfg = config()
    store = TraceStateStore(create_engine('sqlite://'))
    store.create_tables()
    store.job(cfg['job_name'], utc_time(cfg['range_start']), utc_time(cfg['range_end']))
    rows = [step()]
    client = Mock()
    client.history.side_effect = lambda *args: copy.deepcopy(rows)
    client.incremental.return_value = {'list': [], 'hasNextPage': False}
    def respond(prompt):
        task = json.loads(prompt.split('以下 JSON 是任务数据：\n')[1])
        return json.dumps([item(id) for id in task['eligible_fix_ids']])
    call = Mock(side_effect=respond)
    extractor = Extractor(cfg, call, len)
    writer = FakeWriter()
    pipeline = Pipeline(cfg, store, client, extractor, writer)
    key = store.discover('test', [identity(rows[0])], (utc_time(rows[0]['updateTime']), 1))[0]
    return cfg, store, rows, client, call, writer, pipeline, key


def test_two_repairs_create_two_documents_and_rerun_skips(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows.append(step(2, fixResult='PASS'))
    pipeline.process(key)
    assert len(writer.docs) == 2 and call.call_count == 1
    assert all(x['user_id'] == '0' and x['product']['product_id'] == '1058' for x in writer.docs.values())
    assert 'no user' in writer.docs[doc_id(rows[0])]['experience']
    assert 'product' not in writer.docs[doc_id(rows[0])]['metadata']
    pipeline.process(key)
    assert len(writer.puts) == 2 and call.call_count == 1
    assert store.get(key).process_status == 'done'


def test_products_never_share_prompt(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows.append(step(2, groupId=2000))
    pipeline.process(key)
    assert len(writer.docs) == 2 and call.call_count == 2
    for args in call.call_args_list:
        payload = json.loads(args.args[0].split('以下 JSON 是任务数据：\n')[1])
        assert len({s['groupId'] for s in payload['steps']}) == 1


@pytest.mark.parametrize('fix', ['fail', 'FAIL'])
def test_explicit_invalid_removes_owned_experience(setup, fix):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    pipeline.process(key)
    rows[0]['fixResult'] = fix
    pipeline.process(key)
    assert not writer.docs and len(writer.deletes) == 1


@pytest.mark.parametrize('change', ['unknown', 'insufficient', 'malformed', 'missing', 'query_error'])
def test_uncertain_result_preserves_existing(setup, change):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    pipeline.process(key)
    rows[0]['updateTime'] = '2026-09-03 10:25:08'
    if change == 'unknown':
        rows[0]['fixResult'] = 'pending'
    elif change == 'query_error':
        client.history.side_effect = RuntimeError('request failed')
    else:
        call.side_effect = None
        call.return_value = {'insufficient': json.dumps([item(valid=False, reason_code='insufficient_evidence')]),
                             'malformed': 'invalid json', 'missing': '[]'}[change]
    pipeline.process(key)
    assert len(writer.docs) == 1 and not writer.deletes
    if change in ('query_error', 'malformed', 'missing'):
        assert store.get(key).process_status == 'failed'


def test_unrelated_validated_result_deletes(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    pipeline.process(key)
    rows[0]['updateTime'] = '2026-09-03 10:25:08'
    call.side_effect = None
    call.return_value = json.dumps([item(valid=False, reason_code='unrelated')])
    pipeline.process(key)
    assert not writer.docs


def test_write_failure_reuses_saved_model_output(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    writer.fail_put = True
    pipeline.process(key)
    assert store.get(key).process_status == 'failed'
    writer.fail_put = False
    pipeline.process(key)
    assert call.call_count == 1 and len(writer.docs) == 1
    assert store.get(key).process_status == 'done'


def test_es_success_sql_failure_does_not_write_twice(setup, monkeypatch):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    save = store.save
    def fail_after_write(*args, **kwargs):
        if writer.puts:
            raise OperationalError('sql', {}, Exception('unavailable'))
        return save(*args, **kwargs)
    monkeypatch.setattr(store, 'save', fail_after_write)
    with pytest.raises(OperationalError):
        pipeline.process(key)
    monkeypatch.setattr(store, 'save', save)
    pipeline.process(key)
    assert call.call_count == 1 and len(writer.puts) == 1
    assert store.get(key).process_status == 'done'


def test_trial_range_excludes_other_months_but_keeps_context(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows.insert(0, step(2, updateTime='2026-07-31 23:59:59'))
    rows.append(step(3, updateTime='2026-10-01 00:00:00'))
    pipeline.process(key)
    assert len(writer.docs) == 1
    assert '2026-07-31' in call.call_args.args[0]


def test_no_change_pass_does_not_call_model(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows[0]['diffContent'] = {'hasChanged': False, 'changedLines': []}
    pipeline.process(key)
    assert not writer.docs and not call.called


def test_user_assignment_and_existing_owner():
    assert build_body(step(), item(), 'rev', None)['user_id'] == '0'
    assert build_body(step(testUser='alice'), item(), 'rev', {'user_id': '0'})['user_id'] == 'alice'
    assert build_body(step(testUser='alice'), item(), 'rev', {'user_id': 'bob'})['user_id'] == 'bob'


def test_incremental_cursor_moves_with_page_one(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    client.incremental.side_effect = [
        {'list': [step(2)], 'hasNextPage': True},
        {'list': [step(3)], 'hasNextPage': False}]
    pipeline.run()
    assert [x.args[1] for x in client.incremental.call_args_list] == [1, 2]
    assert store.job('test', pipeline.start, pipeline.end).last_id == 3


def test_cursor_transaction_rolls_back_discovery(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    def reject(conn, cursor, statement, parameters, context, many):
        if statement.startswith('UPDATE trace_experience_job_state'):
            raise OperationalError(statement, parameters, Exception('failed'))
    event.listen(store.engine, 'before_cursor_execute', reject)
    with pytest.raises(OperationalError):
        store.discover('test', [identity(step(2, caseId='other'))], (utc_time(step()['updateTime']), 2))
    event.remove(store.engine, 'before_cursor_execute', reject)
    assert store.job('test', pipeline.start, pipeline.end).last_id == 1
    from db_operate.sql_models import TraceExperienceRecord
    with store.sessions() as session:
        assert session.query(TraceExperienceRecord).count() == 1


def test_incorrect_incremental_order_does_not_move_cursor(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    client.incremental.return_value = {'list': [step(3), step(2)], 'hasNextPage': False}
    with pytest.raises(ValueError, match='incremental_order'):
        pipeline.run()
    assert store.job('test', pipeline.start, pipeline.end).last_id == 1


def test_source_paging_preserves_raw_user_and_parses_json():
    client = StepClient(config())
    raw = step(diffContent=json.dumps(step()['diffContent']), customStruct='[]')
    client.page = Mock(side_effect=[
        {'list': [raw], 'total': 2, 'pageNum': 1, 'nextPage': 2, 'hasNextPage': True},
        {'list': [step(2)], 'total': 2, 'pageNum': 2, 'hasNextPage': False}])
    history = client.history('case', 'no user')
    assert isinstance(history[0]['diffContent'], dict)
    assert [c.args[1]['pageNum'] for c in client.page.call_args_list] == [1, 2]
    assert all(c.args[1]['testUser'] == 'no user' for c in client.page.call_args_list)


@pytest.mark.parametrize('pages', [
    [{'list': [], 'total': 1, 'pageNum': 1, 'nextPage': 2, 'hasNextPage': True}],
    [{'list': [step()], 'total': 2, 'pageNum': 1, 'hasNextPage': False}],
    [{'list': [step(), step()], 'total': 2, 'pageNum': 1, 'hasNextPage': False}],
])
def test_incomplete_history_fails(pages):
    client = StepClient(config())
    client.page = Mock(side_effect=pages)
    with pytest.raises(ValueError):
        client.history('case', 'no user')


def test_source_retries_network_but_not_business_error():
    session = Mock()
    response = Mock(status_code=200)
    response.json.return_value = {'success': True, 'content': {'list': [], 'hasNextPage': False}}
    session.request.side_effect = [requests.Timeout(), response]
    client = StepClient(config(), session)
    client.incremental(utc_time('2026-09-02 00:00:00'), 10)
    assert session.request.call_count == 2
    assert session.request.call_args.kwargs['json']['pageNum'] == 1


def test_overlong_single_repair_fails_without_deletion(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    pipeline.process(key)
    rows[0]['diffContent']['systemErrors'] = 'x' * 100000
    pipeline.process(key)
    assert len(writer.docs) == 1 and store.get(key).process_status == 'failed'
    assert call.call_count == 1


def test_model_boolean_strings_or_unknown_refs_rejected():
    for change in ({'valid': 'false'}, {'related_step_ids': ['999']}, {'title': ''}):
        extractor = Extractor(config(), lambda p: json.dumps([item(**change)]), len)
        with pytest.raises(ValueError):
            extractor.extract([step()], ['1'])


def test_large_trace_splits_repair_batches(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows.extend(step(i) for i in range(2, 7))
    # 只让最多三条 Step 的批次通过预算检查，仍调用真实提取和校验。
    pipeline.extractor.fits = lambda steps, ids: len(steps) <= 3
    pipeline.process(key)
    assert len(writer.docs) == 6 and call.call_count == 6
    assert store.get(key).process_status == 'done'


def test_one_bad_batch_preserves_completed_repairs(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows.extend(step(i) for i in range(2, 5))
    pipeline.extractor.fits = lambda steps, ids: len(steps) <= 3
    respond = call.side_effect
    count = 0
    def fail_second(prompt):
        nonlocal count
        count += 1
        return '[]' if count == 2 else respond(prompt)
    call.side_effect = fail_second
    pipeline.process(key)
    assert len(writer.docs) == 1 and store.get(key).process_status == 'failed'
    pipeline.process(key)
    assert len(writer.docs) == 4 and writer.puts.count(doc_id(rows[0])) == 1


def test_source_reverting_after_partial_write_is_reprocessed(setup):
    cfg, store, rows, client, call, writer, pipeline, key = setup
    rows.append(step(2))
    pipeline.process(key)
    original = copy.deepcopy(rows)
    rows[0]['updateTime'] = '2026-09-03 10:25:08'
    put = writer.put
    def fail_second(body):
        if body['doc_id'] == doc_id(rows[1]):
            raise RuntimeError('write failed')
        put(body)
    writer.put = fail_second
    pipeline.process(key)
    rows[:] = original
    writer.put = put
    store.discover('test', [identity(rows[0])], (utc_time(rows[0]['updateTime']), 1))
    pipeline.process(key)
    assert store.get(key).process_status == 'done'
    assert len({d['metadata']['source_revision'] for d in writer.docs.values()}) == 1



def test_model_analysis_text_before_json_is_accepted():
    output = parse_model_array('我们先分析轨迹。\n' + json.dumps([item()]))
    assert output == [item()]


def test_model_array_with_trailing_text_is_rejected():
    with pytest.raises(ValueError, match='invalid_model_array'):
        parse_model_array(json.dumps([item()]) + '\n额外说明')
