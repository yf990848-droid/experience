"""调测经验任务的两张状态表；每次操作使用独立短事务。"""
import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from db_operate.sql_models import TraceExperienceJobState as Job, TraceExperienceRecord as Record


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(json_text(value).encode('utf-8')).hexdigest()


class TraceStateStore:
    def __init__(self, engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_tables(self):
        # 仅创建本任务的表，避免触及其他现有业务表。
        Job.__table__.create(self.engine, checkfirst=True)
        Record.__table__.create(self.engine, checkfirst=True)

    def job(self, name, start, end):
        with self.sessions.begin() as session:
            row = session.get(Job, name)
            if row is None:
                row = Job(job_name=name, range_start=start, range_end=end,
                          last_update_time=start, last_id=0)
                session.add(row)
            elif row.range_start != start or row.range_end != end:
                raise ValueError('range_changed: 请为新时间范围设置不同 job_name')
        return row

    def discover(self, job_name, steps, cursor):
        keys = []
        with self.sessions.begin() as session:
            for step in steps:
                trace_key = digest([step['case_id'], step['test_user']])
                key = digest([job_name, trace_key])
                if key not in keys:
                    keys.append(key)
                row = session.get(Record, key)
                if row is None:
                    row = Record(record_key=key, job_name=job_name, trace_key=trace_key,
                                 case_id=step['case_id'],
                                 source_test_user_json=json_text(step['test_user']),
                                 experience_refs='[]')
                    session.add(row)
                row.process_status = 'pending'
                row.source_update_time = max(row.source_update_time or step['updated_at'], step['updated_at'])
                row.updated_at = datetime.utcnow()
            job = session.get(Job, job_name)
            job.last_update_time, job.last_id = cursor
            job.updated_at = datetime.utcnow()
        return keys

    def pending(self, job_name, limit, cutoff):
        with self.sessions() as session:
            return list(session.scalars(select(Record.record_key).where(
                Record.job_name == job_name, Record.process_status.in_(['pending', 'failed']),
                Record.updated_at <= cutoff
            ).order_by(Record.updated_at, Record.record_key).limit(limit)))

    def get(self, key):
        with self.sessions() as session:
            return session.get(Record, key)

    def save(self, key, refs, status=None, revision=None, error=None):
        with self.sessions.begin() as session:
            row = session.get(Record, key)
            row.experience_refs = json_text(refs)
            row.updated_at = datetime.utcnow()
            if status:
                row.process_status = status
                row.last_error = error
                row.retry_count = (row.retry_count or 0) + 1 if status == 'failed' else 0
            if revision is not None:
                row.processed_trace_hash = revision
