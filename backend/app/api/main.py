import os
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.app.config import Settings
from backend.app.service import Service, public_project
from backend.app.jobs.worker import Worker
from backend.app.storage.repository import uid, encode
from backend.app import schema as S

PREFIX = '/api/v1'


def create_app(settings=None, run_worker=True):
    settings = settings or Settings.from_env()
    service = Service(settings)
    repo = service.repo
    worker = Worker(service)

    @asynccontextmanager
    async def lifespan(app):
        # flock prevents duplicate scanners/workers on one database across processes.
        import fcntl
        lock = (settings.data_dir / 'service.lock').open('a')
        try:
            if run_worker:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if run_worker:
                worker.start()
            yield
        finally:
            if run_worker:
                worker.stop()
            lock.close()

    app = FastAPI(title='拍够了吗？', version='0.1.0', lifespan=lifespan,
                  responses={409: {'model': S.ErrorResponse}, 422: {'model': S.ErrorResponse}})
    app.state.service, app.state.worker = service, worker
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Content-Type', 'Idempotency-Key'])

    def error_response(exc, request_id=None):
        return JSONResponse(status_code=exc.status, content=dict(
            error=dict(code=exc.code, message=exc.message, retryable=exc.retryable,
                       action=exc.action, job_id=None), request_id=request_id or uid('request')))

    @app.middleware('http')
    async def origin_guard(request, call_next):
        request.state.request_id = uid('request')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if (origin and origin not in settings.allowed_origins) or request.headers.get('sec-fetch-site') == 'cross-site':
                return error_response(S.DomainError('INVALID_INPUT', '不允许此网页来源访问本地写接口', 403))
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.exception_handler(S.DomainError)
    async def domain_error(request, exc):
        return error_response(exc, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(S.DomainError('INVALID_INPUT', '请求字段、ID 或时间范围无效', 422), request.state.request_id)

    def mutate(request, body, key, action):
        fingerprint = encode(dict(path=request.url.path, body=body))
        return service.mutate(key, fingerprint, action)

    def paginate(items, cursor, limit, identity):
        start = 0
        if cursor:
            indexes = [i for i, item in enumerate(items) if item[identity] == cursor]
            if not indexes:
                raise S.DomainError('INVALID_INPUT', '分页游标无效', 422)
            start = indexes[0] + 1
        page = items[start:start + limit]
        return page, page[-1][identity] if page and start + limit < len(items) else None

    @app.get(PREFIX + '/health', response_model=S.Health)
    def health():
        with repo.transaction() as db:
            db.execute('SELECT 1')
        return dict(status='ok', model_mode=service.model_mode, database='ok',
                    worker='running' if worker.thread and worker.thread.is_alive() else 'stopped')

    @app.post(PREFIX + '/projects', response_model=S.Project, status_code=201)
    def create_project(body: S.CreateProject, request: Request, idempotency_key: str | None = Header(None)):
        return mutate(request, body.model_dump(), idempotency_key,
                      lambda db: service.create_project(db, body.model_dump()))

    @app.get(PREFIX + '/projects', response_model=S.ProjectPage)
    def projects(cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
        with repo.transaction() as db:
            items, next_cursor = paginate([public_project(p) for p in repo.projects(db)], cursor, limit, 'id')
            return dict(items=items, next_cursor=next_cursor)

    @app.post(PREFIX + '/projects/{pid}/plan:generate', response_model=S.Job, status_code=202)
    def generate(pid: S.ID, body: S.Revision, request: Request, idempotency_key: str | None = Header(None)):
        return mutate(request, body.model_dump(), idempotency_key,
                      lambda db: service.queue_plan(db, pid, body.expected_revision))

    @app.patch(PREFIX + '/projects/{pid}/plan', response_model=S.Project)
    def edit_plan(pid: S.ID, body: S.PlanEdit, request: Request, idempotency_key: str | None = Header(None)):
        return mutate(request, body.model_dump(), idempotency_key,
                      lambda db: service.edit_plan(db, pid, body.model_dump()))

    @app.post(PREFIX + '/projects/{pid}/plan:confirm', response_model=S.Project)
    def confirm(pid: S.ID, body: S.Revision, request: Request, idempotency_key: str | None = Header(None)):
        return mutate(request, body.model_dump(), idempotency_key,
                      lambda db: service.confirm_plan(db, pid, body.expected_revision))

    @app.post(PREFIX + '/projects/{pid}/analysis:authorize', response_model=S.Project)
    def authorize_analysis(pid: S.ID, body: S.Revision, request: Request, idempotency_key: str | None = Header(None)):
        def action(db):
            p = repo.project(db, pid)
            repo.expect(p, body.expected_revision)
            p['model_upload_consent'] = True
            repo.save(db, p)
            return public_project(p)
        return mutate(request, body.model_dump(), idempotency_key, action)

    @app.get(PREFIX + '/projects/{pid}/snapshot', response_model=S.Snapshot)
    def snapshot(pid: S.ID):
        data = service.snapshot(pid)
        data['clips'] = [S.Clip.model_validate({k: v for k, v in c.items() if k in S.Clip.model_fields})
                         for c in data['clips']]
        return data

    @app.get(PREFIX + '/projects/{pid}/clips', response_model=S.ClipPage)
    def clips(pid: S.ID, cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
        with repo.transaction() as db:
            items, next_cursor = paginate(repo.project(db, pid)['clips'], cursor, limit, 'id')
            return dict(items=[{k: v for k, v in c.items() if k in S.Clip.model_fields} for c in items],
                        next_cursor=next_cursor)

    @app.get(PREFIX + '/clips/{cid}', response_model=S.Clip)
    def clip(cid: S.ID):
        with repo.transaction() as db:
            c = next((c for p in repo.projects(db) for c in p['clips'] if c['id'] == cid), None)
            if not c:
                raise S.DomainError('NOT_FOUND', '素材不存在', 404)
            return {k: v for k, v in c.items() if k in S.Clip.model_fields}

    @app.patch(PREFIX + '/projects/{pid}/clips/{cid}/membership')
    def membership(pid: S.ID, cid: S.ID, body: S.MembershipEdit, request: Request,
                   idempotency_key: str | None = Header(None)):
        return mutate(request, body.model_dump(), idempotency_key,
                      lambda db: service.membership(db, pid, cid, body.model_dump()))

    @app.get(PREFIX + '/jobs/{jid}', response_model=S.Job)
    def job(jid: S.ID):
        with repo.transaction() as db:
            return repo.job(db, jid)

    @app.post(PREFIX + '/jobs/{jid}/retry', response_model=S.Job, status_code=202)
    def retry(jid: S.ID, body: S.Retry, request: Request, idempotency_key: str | None = Header(None)):
        def action(db):
            job = repo.job(db, jid)
            if job['state'] != 'failed' or job['attempt'] != body.expected_attempt:
                raise S.DomainError('CONFLICT', '只能重试当前已失败的任务')
            db.execute("UPDATE jobs SET state='queued', next_attempt_at=0, error=NULL WHERE id=?", (jid,))
            return repo.job(db, jid)
        return mutate(request, body.model_dump(), idempotency_key, action)

    @app.get(PREFIX + '/renditions/{rid}/content')
    def content(rid: S.ID):
        with repo.transaction() as db:
            rendition = next((r for p in repo.projects(db) for r in p['renditions'] if r['id'] == rid), None)
        if not rendition or not Path(rendition['path']).is_file():
            raise S.DomainError('NOT_FOUND', '本地分析副本不存在', 404)
        return FileResponse(rendition['path'], media_type='video/mp4')

    @app.post(PREFIX + '/projects/{pid}/imports', response_model=S.ImportBatch, status_code=202)
    def upload(pid: S.ID, request: Request, expected_revision: int = Form(...),
               projection: str = Form('unknown'), files: list[UploadFile] = File(...),
               idempotency_key: str | None = Header(None)):
        # Unknown projection is deliberately blocked; a filename cannot establish viewing geometry.
        if projection not in ('rectilinear', 'unknown'):
            raise S.DomainError('INVALID_INPUT', '不支持的投影声明', 422)
        import hashlib
        staged, failures = [], []
        for upload in files:
            cid, sha, size = uid('clip'), hashlib.sha256(), 0
            target = settings.data_dir / 'imports' / f'{cid}.upload'
            try:
                with target.open('xb') as dest:
                    while block := upload.file.read(1024 * 1024):
                        size += len(block)
                        if size > settings.max_source_bytes:
                            raise S.DomainError('INVALID_INPUT', '文件超过源文件大小上限', 413)
                        if shutil.disk_usage(target.parent).free < settings.min_free_bytes + len(block):
                            raise S.DomainError('STORAGE_FULL', '可用空间不足', 507)
                        sha.update(block)
                        dest.write(block)
                if not size:
                    raise S.DomainError('INVALID_INPUT', '空文件不能导入', 422)
                staged.append(dict(cid=cid, filename=Path(upload.filename or '本地视频').name,
                                   target=target, size=size, sha256=sha.hexdigest()))
            except S.DomainError as exc:
                target.unlink(missing_ok=True)
                failures.append(dict(filename=Path(upload.filename or '本地视频').name, status='failed',
                                     error=dict(code=exc.code, message=exc.message, retryable=exc.retryable,
                                                action=exc.action, job_id=None)))
        try:
            fingerprint = dict(expected_revision=expected_revision, projection=projection,
                               files=[(x['filename'], x['size'], x['sha256']) for x in staged],
                               failures=[x['filename'] for x in failures])
            def action(db):
                p = repo.project(db, pid)
                repo.expect(p, expected_revision)
                if not p['confirmed']:
                    raise S.DomainError('CONFLICT', '先确认分镜清单')
                items = list(failures)
                for item in staged:
                    old = next((c for c in p['clips'] if c['group_key'] == f"local:{item['sha256']}"), None)
                    if old:
                        items.append(dict(filename=item['filename'], status='duplicate', clip_id=old['id'], job_id=old['job_id']))
                        continue
                    c = dict(id=item['cid'], name=item['filename'], group_key=f"local:{item['sha256']}", source='local',
                             size=item['size'], sha256=item['sha256'], state='awaiting_ready', active=True, generation=1,
                             rendition_id=None, duration=None, error=None, job_id=None,
                             local_source=str(item['target']), projection=projection)
                    p['clips'].append(c)
                    service.queue_clip(db, p, c)
                    items.append(dict(filename=item['filename'], status='accepted', clip_id=c['id'], job_id=c['job_id']))
                if any(item['status'] == 'accepted' for item in items):
                    repo.save(db, p)
                return dict(revision=p['revision'], items=items)
            result = mutate(request, fingerprint, idempotency_key, action)
            referenced = {i['clip_id'] for i in result['items'] if i['status'] == 'accepted'}
            for item in staged:
                if item['cid'] not in referenced:
                    item['target'].unlink(missing_ok=True)
            return result
        except BaseException:
            for item in staged:
                item['target'].unlink(missing_ok=True)
            raise

    dist = Path(__file__).resolve().parents[3] / 'frontend' / 'dist'

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        if path.startswith('api/'):
            raise S.DomainError('NOT_FOUND', '接口不存在', 404)
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        if (dist / 'index.html').is_file():
            return FileResponse(dist / 'index.html')
        return JSONResponse({'message': '请先构建前端，或运行 scripts/dev'}, status_code=503)

    return app


if os.getenv('BOLD_OPENAPI_ONLY') != '1':
    app = create_app()
