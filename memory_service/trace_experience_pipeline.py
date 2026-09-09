"""定时读取调测记录，按一次有效修复保存经验。依赖在运行入口加载。"""
import argparse
import copy
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta

import requests
from sqlalchemy.exc import SQLAlchemyError

from db_operate.trace_experience_store import TraceStateStore, digest, json_text
from project_configs.prompt_configs import TRACE_EXPERIENCE_PROMPT

LOG = logging.getLogger(__name__)
SOURCE = 'trace_experience'
VALID = {'success', 'pass'}
INVALID = {'fail'}
TEXT_FIELDS = ('title', 'failure_phenomenon', 'summary', 'debug_trace', 'error_log',
               'diff', 'root_cause', 'pattern', 'rag_search_text')


def utc_time(value):
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S') - timedelta(hours=8)


def source_time(value):
    return (value + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def user_id(value):
    return '0' if value is None or str(value).strip().lower() in ('', 'no user') else str(value)


def doc_id(step):
    return 'tracefix_' + digest([SOURCE, str(step['groupId']), str(step['id'])])[:48]


def identity(raw):
    if not isinstance(raw, dict) or type(raw.get('id')) is not int or raw['id'] <= 0:
        raise ValueError('invalid_step_id')
    if not isinstance(raw.get('caseId'), str) or not raw['caseId']:
        raise ValueError('invalid_case_id')
    if 'testUser' not in raw or raw['testUser'] is not None and not isinstance(raw['testUser'], str):
        raise ValueError('invalid_test_user')
    return {'case_id': raw['caseId'], 'test_user': raw['testUser'],
            'updated_at': utc_time(raw['updateTime']), 'id': raw['id']}


def normalize(raw):
    identity(raw)
    step = copy.deepcopy(raw)
    if step.get('groupId') is None:
        raise ValueError('missing_group_id')
    for field in ('diffContent', 'customStruct'):
        value = step.get(field)
        if isinstance(value, str):
            value = json.loads(value)
        step[field] = value
    if step['diffContent'] is not None and not isinstance(step['diffContent'], dict):
        raise ValueError('invalid_diff_content')
    diff = step['diffContent'] or {}
    if 'changedLines' in diff and (not isinstance(diff['changedLines'], list) or
                                  any(not isinstance(line, str) for line in diff['changedLines'])):
        raise ValueError('invalid_changed_lines')
    for field in ('startTime', 'endTime'):
        if step.get(field) is not None and type(step[field]) is not int:
            raise ValueError('invalid_step_time')
    return step


def result(step):
    return str(step.get('fixResult') or '').strip().lower()


def parse_model_array(text):
    """允许模型在最终 JSON 数组前输出说明文字。"""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != '[':
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and not text[index + end:].strip():
            return value
    raise ValueError('invalid_model_array')


def eligible(step, start, end):
    changed = step.get('diffContent') or {}
    when = utc_time(step['updateTime'])
    return (start <= when and (end is None or when < end) and result(step) in VALID
            and changed.get('hasChanged') is True and bool(changed.get('changedLines')))


class StepClient:
    def __init__(self, config, session=None):
        self.cfg = config
        self.session = session or requests.Session()
        headers = json.loads(os.environ.get(config.get('headers_env', ''), '{}'))
        if not isinstance(headers, dict):
            raise ValueError('source_headers_must_be_object')
        self.headers = headers

    def page(self, endpoint, parameters):
        for attempt in range(self.cfg.get('retry_attempts', 3)):
            try:
                response = self.session.request(
                    self.cfg.get('source_method', 'POST'),
                    self.cfg['source_url'].rstrip('/') + '/' + endpoint,
                    json=parameters, headers=self.headers,
                    timeout=self.cfg.get('request_timeout', 30),
                    verify=self.cfg.get('verify_tls', True))
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.ConnectionError('source_temporarily_unavailable')
                response.raise_for_status()
                body = response.json()
                if body.get('success') is not True or not isinstance(body.get('content'), dict):
                    raise ValueError('source_response_failed')
                page = body['content']
                if not isinstance(page.get('list'), list) or type(page.get('hasNextPage')) is not bool:
                    raise ValueError('invalid_page')
                return page
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == self.cfg.get('retry_attempts', 3):
                    raise
        raise ValueError('invalid_retry_attempts')

    def incremental(self, time, last_id):
        return self.page('listByUpdateTimeAndId', {
            'updateTime': source_time(time), 'id': last_id,
            'pageNum': 1, 'pageSize': self.cfg['page_size']})

    def history(self, case_id, test_user):
        page_num, total, records = 1, None, {}
        while True:
            page = self.page('listByCaseIdAndTestUser', {
                'caseId': case_id, 'testUser': test_user,
                'pageNum': page_num, 'pageSize': self.cfg['page_size']})
            if type(page.get('total')) is not int or page['total'] < 0:
                raise ValueError('invalid_history_total')
            if total is None:
                total = page['total']
            if total != page['total'] or page.get('pageNum') != page_num:
                raise ValueError('history_changed_during_paging')
            for raw in page['list']:
                step = normalize(raw)
                if step['caseId'] != case_id or step['testUser'] != test_user:
                    raise ValueError('history_identity_mismatch')
                if step['id'] in records:
                    raise ValueError('duplicate_history_step')
                records[step['id']] = step
            if not page['hasNextPage']:
                break
            if not page['list'] or page.get('nextPage') != page_num + 1:
                raise ValueError('incomplete_history_page')
            page_num += 1
        if len(records) != total:
            raise ValueError('incomplete_history')
        return sorted(records.values(), key=lambda s: (
            s.get('startTime') or 0, s.get('endTime') or 0, s['updateTime'], s['id']))


class Extractor:
    def __init__(self, config, call, count_tokens):
        self.cfg, self.call, self.count_tokens = config, call, count_tokens

    def prompt(self, steps, ids):
        return TRACE_EXPERIENCE_PROMPT + json_text({'eligible_fix_ids': ids, 'steps': steps})

    def fits(self, steps, ids):
        return (self.count_tokens(self.prompt(steps, ids)) + self.cfg['max_output_tokens']
                + self.cfg.get('safety_margin', 2048) <= self.cfg['context_limit'])

    def batches(self, steps, selected):
        ids = [str(s['id']) for s in selected]
        if not ids:
            return
        if self.fits(steps, ids):
            yield steps, ids
            return
        # 超大轨迹按相邻修复之间的过程拆分，保留上一修复和下一条记录作上下文。
        previous = 0
        selected_ids = set(ids)
        for i, step in enumerate(steps):
            if result(step) not in VALID:
                continue
            if str(step['id']) in selected_ids:
                yield steps[previous:min(i + 2, len(steps))], [str(step['id'])]
            previous = i

    def extract(self, steps, ids):
        if not self.fits(steps, ids):
            raise ValueError('single_repair_exceeds_context')
        text = self.call(self.prompt(steps, ids))
        output = parse_model_array(text)
        known, seen = {str(s['id']) for s in steps}, set()
        for item in output:
            if not isinstance(item, dict):
                raise ValueError('invalid_model_item')
            fix_id = item.get('fix_step_id')
            if fix_id not in ids or fix_id in seen or type(item.get('valid')) is not bool:
                raise ValueError('invalid_model_fix_id')
            seen.add(fix_id)
            refs = item.get('related_step_ids')
            if (not isinstance(refs, list) or any(not isinstance(x, str) or x not in known for x in refs)
                    or fix_id not in refs):
                raise ValueError('invalid_model_references')
            if not isinstance(item.get('reason'), str) or not item['reason'].strip():
                raise ValueError('missing_model_reason')
            if item['valid']:
                if any(not isinstance(item.get(f), str) or not item[f].strip() for f in TEXT_FIELDS):
                    raise ValueError('incomplete_model_experience')
            elif item.get('reason_code') not in ('unrelated', 'insufficient_evidence'):
                raise ValueError('invalid_model_reason_code')
        if seen != set(ids):
            raise ValueError('incomplete_model_result')
        return output


class ExperienceWriter:
    """复用已有经验写入、归档和质量检查。"""
    def __init__(self):
        from api.experience_api import upsert_experience, delete_experience
        from memory_service.experience_manage import get_es_client
        from memory_service.service_params import DocumentCreate
        from memory_service.quality_checker import run_quality_check_and_update
        from project_configs.settings import UNIFIED_INDEX
        from constants import USER_ID
        self.upsert, self.remove = upsert_experience, delete_experience
        self.model, self.check = DocumentCreate, run_quality_check_and_update
        self.es, self.index, self.user_field = get_es_client(), UNIFIED_INDEX, USER_ID

    def get(self, key):
        from elasticsearch import NotFoundError
        try:
            source = self.es.get(index=self.index, id=key)['_source']
            source['user_id'] = source.get(self.user_field, '0')
            return source
        except NotFoundError:
            return None

    def put(self, body):
        self.upsert(self.model(**copy.deepcopy(body)))

    def delete(self, key):
        from elasticsearch import NotFoundError
        try:
            self.remove(key)
        except NotFoundError:
            pass

    def quality(self, body):
        self.check(body['doc_id'], '\n'.join(body[f] for f in ('title', 'summary', 'experience')))


def build_body(step, item, revision, existing):
    owner = user_id(step['testUser'])
    if existing and user_id(existing.get('user_id')) != '0':
        owner = existing['user_id']
    trace = item['debug_trace'] + '\n\n来源：' + json_text({
        'case_id': step['caseId'], 'test_user': step['testUser'],
        'fix_step_id': str(step['id']), 'related_step_ids': item['related_step_ids'],
        'fix_result': step['fixResult'], 'update_time': step['updateTime']})
    content = '\n\n'.join('## ' + title + '\n' + value for title, value in (
        ('Debug Trace', trace), ('Error Log', item['error_log']), ('Diff', item['diff']),
        ('Root Cause', item['root_cause']), ('Pattern', item['pattern'])))
    metadata = {'source': SOURCE, 'group_id': str(step['groupId']),
                'fix_step_id': str(step['id']), 'source_revision': revision,
                'failure_phenomenon': item['failure_phenomenon'],
                'related_step_ids': item['related_step_ids']}
    if step.get('product') is not None:
        metadata['product'] = step['product']
    body = {'doc_id': doc_id(step), 'scene_id': '421', 'scene': '测试脚本调测经验',
            'user_id': owner, 'product': {'product_id': str(step['groupId'])},
            'title': item['title'], 'summary': item['summary'], 'experience': content,
            'rag_search_text': item['rag_search_text'], 'metadata': metadata}
    metadata['payload_hash'] = digest(body)
    return body


class Pipeline:
    def __init__(self, config, store, client, extractor, writer):
        self.cfg, self.store, self.client = config, store, client
        self.extractor, self.writer = extractor, writer
        self.summary = dict(discovered=0, completed=0, failed=0,
                            created=0, updated=0, deleted=0, skipped=0)
        self.start = utc_time(config['range_start'])
        self.end = utc_time(config['range_end']) if config.get('range_end') else None
        if self.end is not None and self.end <= self.start:
            raise ValueError('invalid_time_range')

    def owned(self, step):
        existing = self.writer.get(doc_id(step))
        if existing and (existing.get('metadata', {}).get('source') != SOURCE or
                         existing.get('metadata', {}).get('fix_step_id') != str(step['id']) or
                         existing.get('metadata', {}).get('group_id') != str(step['groupId'])):
            raise ValueError('document_owner_mismatch')
        return existing

    def apply(self, step, ref):
        existing = self.owned(step)
        if ref['action'] == 'delete':
            if existing:
                self.writer.delete(doc_id(step))
                self.summary['deleted'] += 1
        elif ref['action'] == 'put':
            body = ref['body']
            if not existing or existing.get('metadata', {}).get('payload_hash') != body['metadata']['payload_hash']:
                self.writer.put(body)
                self.summary['updated' if existing else 'created'] += 1
            else:
                self.summary['skipped'] += 1
            # ES 成功、SQL 保存失败后重试时，也补上质量检查。
            self.writer.quality(body)
        ref['done'] = True

    def process(self, key):
        row = self.store.get(key)
        refs = json.loads(row.experience_refs)
        try:
            steps = self.client.history(row.case_id, json.loads(row.source_test_user_json))
            revision = digest([steps, self.cfg['extraction_version'], self.cfg['model_name'],
                               self.cfg['range_start'], self.cfg.get('range_end'),
                               self.cfg['context_limit'], self.cfg['max_output_tokens']])
            by_id = {str(s['id']): s for s in steps}
            groups = defaultdict(list)
            for step in steps:
                groups[str(step['groupId'])].append(step)
            for group_steps in groups.values():
                # 修复结论明确变为无效时撤销本任务生成的经验。
                for step in group_steps:
                    if result(step) in INVALID:
                        self.apply(step, {'action': 'delete'})
                selected = []
                for step in group_steps:
                    if not eligible(step, self.start, self.end):
                        continue
                    saved = next((r for r in refs if r['doc_id'] == doc_id(step) and r['revision'] == revision), None)
                    if saved:
                        if not saved.get('done'):
                            self.apply(step, saved)
                            self.store.save(key, refs)
                        else:
                            self.summary['skipped'] += 1
                    else:
                        selected.append(step)
                for batch, ids in self.extractor.batches(group_steps, selected):
                    items = self.extractor.extract(batch, ids)
                    for item in items:
                        step = by_id[item['fix_step_id']]
                        ref = {'doc_id': doc_id(step), 'revision': revision, 'done': False}
                        if item['valid']:
                            ref.update(action='put', body=build_body(step, item, revision, self.owned(step)))
                        elif item['reason_code'] == 'unrelated':
                            ref['action'] = 'delete'
                        else:
                            ref.update(action='keep', reason=item['reason'])
                        refs = [r for r in refs if r['doc_id'] != ref['doc_id']] + [ref]
                        self.store.save(key, refs)  # 先保存模型结果；写入失败后可直接重试。
                        self.apply(step, ref)
                        self.store.save(key, refs)
            self.store.save(key, refs, status='done', revision=revision)
            self.summary['completed'] += 1
        except SQLAlchemyError:
            raise
        except Exception as exc:
            # 不记录响应正文、日志、密钥；错误类型供管理员定位对应模块。
            code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__
            self.store.save(key, refs, status='failed', error=code[:200])
            self.summary['failed'] += 1
            LOG.warning('trace experience failed record=%s error=%s', key, code)

    def run(self):
        job = self.store.job(self.cfg['job_name'], self.start, self.end)
        cutoff = datetime.utcnow()
        remaining = self.cfg.get('retry_trace_limit', 100)
        while remaining > 0:
            keys = self.store.pending(job.job_name, min(remaining, 100), cutoff)
            if not keys:
                break
            for key in keys:
                self.process(key)
            remaining -= len(keys)
        cursor = (job.last_update_time, job.last_id)
        for _ in range(self.cfg.get('max_pages_per_run', 100)):
            page = self.client.incremental(*cursor)
            rows, previous, stop = [], cursor, False
            for raw in page['list']:
                step = identity(raw)
                point = (step['updated_at'], step['id'])
                if point <= previous:
                    raise ValueError('incremental_order_or_cursor_invalid')
                previous = point
                if self.end is not None and point[0] >= self.end:
                    stop = True
                    continue
                rows.append(step)
            if rows:
                cursor = (rows[-1]['updated_at'], rows[-1]['id'])
                keys = self.store.discover(job.job_name, rows, cursor)
                self.summary['discovered'] += len(keys)
                for key in keys:
                    self.process(key)
            if stop or not page['hasNextPage']:
                break
            if not rows:
                raise ValueError('empty_incremental_middle_page')
        LOG.info('trace experience summary=%s', self.summary)
        return dict(self.summary)


def run_pipeline_once(config=None, init_tables=False):
    if config is None:
        from project_configs.settings import TASK_RUNNER_CONFIG
        config = TASK_RUNNER_CONFIG['TRACE_EXPERIENCE_EXTRACT']
    from db.sql_connector import get_sql_connector
    store = TraceStateStore(get_sql_connector().engine)
    if init_tables:
        store.create_tables()
        return
    if not isinstance(config.get('context_limit'), int) or config['context_limit'] <= 0:
        raise ValueError('请配置模型实际 context_limit 后运行')
    from models.llm_caller import LLMCaller
    from utils.token_utils import token_count
    caller = LLMCaller(scene='测试脚本调测经验', model_name=config['model_name'])
    extractor = Extractor(config, lambda prompt: caller.model_call(
        prompt, timeout=config['llm_timeout'], max_output_tokens=config['max_output_tokens']), token_count)
    return Pipeline(config, store, StepClient(config), extractor, ExperienceWriter()).run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--init-tables', action='store_true',
                      help='创建本任务的两张状态表（不传参数时默认执行）')
    mode.add_argument('--once', action='store_true', help='手动运行一轮，无需启用定时开关')
    parser.add_argument('--max-pages', type=int, default=None, help='限制本轮增量页数')
    args = parser.parse_args()
    from project_configs.settings import TASK_RUNNER_CONFIG
    cfg = dict(TASK_RUNNER_CONFIG['TRACE_EXPERIENCE_EXTRACT'])
    if args.max_pages is not None:
        if args.max_pages < 1:
            parser.error('--max-pages 必须大于 0')
        cfg['max_pages_per_run'] = args.max_pages
    logging.basicConfig(level=logging.INFO)
    run_pipeline_once(cfg, init_tables=args.init_tables or not args.once)
