import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from backend.app.schema import DomainError


def uid(prefix):
    return f'{prefix}_{uuid.uuid4().hex}'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Repository:
    def __init__(self, root):
        self.root = root
        for directory in ('imports', 'originals', 'renditions', 'tmp', 'logs', 'simulator'):
            (root / directory).mkdir(parents=True, exist_ok=True)
        self.path = root / 'app.sqlite'
        with self.transaction() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
                INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS catalogs(id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, project_id TEXT, kind TEXT NOT NULL,
                    key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, lease_until REAL, next_attempt_at REAL DEFAULT 0,
                    error TEXT, result TEXT, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency(
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL);
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def project(self, db, pid):
        row = db.execute('SELECT document FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            raise DomainError('NOT_FOUND', '项目不存在', 404)
        return json.loads(row[0])

    def save(self, db, p, bump=True):
        if bump:
            p['revision'] += 1
        db.execute('INSERT INTO projects VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (p['id'], encode(p)))

    def projects(self, db):
        return [json.loads(row[0]) for row in db.execute('SELECT document FROM projects ORDER BY rowid DESC')]

    @staticmethod
    def expect(p, revision):
        if p['revision'] != revision:
            raise DomainError('STALE_REVISION', '页面已更新，请重新查看后再操作', action='refresh')

    def enqueue(self, db, kind, payload, key, pid=None):
        old = db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
        if old:
            if old['payload'] != encode(payload):
                raise DomainError('CONFLICT', '相同任务键对应不同输入')
            return old['id']
        jid = uid('job')
        db.execute('INSERT INTO jobs(id,project_id,kind,key,payload,state,created_at) VALUES (?,?,?,?,?,?,?)',
                   (jid, pid, kind, key, encode(payload), 'queued', time.time()))
        return jid

    def job(self, db, jid):
        row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise DomainError('NOT_FOUND', '任务不存在', 404)
        return self.job_dict(row)

    @staticmethod
    def job_dict(row):
        return {k: json.loads(row[k]) if row[k] else None for k in ('error', 'result')} | {
            k: row[k] for k in ('id', 'project_id', 'kind', 'state', 'attempt')}
