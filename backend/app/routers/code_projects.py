"""Project upload and task/result APIs. All source reads are constrained to the manifest."""
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from ..db import IngestJob, SessionLocal, User
from ..deps import current_user, require_roles
from ..ingest import code_project as projects
from ..response import KbError, ok

router = APIRouter(prefix='/code-projects', tags=['code-projects'])


def get_project(job_id: str) -> IngestJob:
    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
    if job is None or job.source_type != 'code_project':
        raise KbError('40401', '工程任务不存在')
    return job


@router.post('')
async def upload(request: Request, file: UploadFile = File(...), project: str = Form(...),
                 version: str = Form(...), library: str = Form('code-projects'),
                 encoding: str = Form('utf-8'), user: User = Depends(require_roles('dev', 'gov', 'admin'))):
    if not (file.filename or '').lower().endswith('.zip'):
        raise KbError('40001', '代码工程请上传 ZIP 文件')
    content = await file.read(projects.MAX_UPLOAD + 1)
    try:
        job_id = await run_in_threadpool(projects.create_project, content, file.filename, project,
                                        version, library, encoding, user.username)
    except ValueError as exc:
        raise KbError('40001', str(exc)) from exc
    payload = projects.job_payload(get_project(job_id))
    projects.submit(job_id)
    return ok(payload, request)


@router.get('')
def list_projects(request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        jobs = db.scalars(select(IngestJob).where(IngestJob.source_type == 'code_project')
                          .order_by(IngestJob.created_at.desc()).limit(100)).all()
    return ok([projects.job_payload(job) for job in jobs], request)


@router.get('/{job_id}')
def detail(job_id: str, request: Request, user: User = Depends(current_user)):
    job = get_project(job_id)
    payload = projects.job_payload(job)
    if job.status == 'done':
        result = projects.load_result(job_id)
        payload.update({k: result[k] for k in ('summary', 'files', 'unresolved', 'embedding', 'engine_version')})
    return ok(payload, request)


@router.post('/{job_id}/retry')
def retry(job_id: str, request: Request, user: User = Depends(require_roles('dev', 'gov', 'admin'))):
    job = get_project(job_id)
    if job.status != 'failed':
        raise KbError('40901', '只能重试失败的任务')
    opts = job.options_json
    new_id = projects.create_project((projects.snapshot_root(job_id) / 'upload.zip').read_bytes(),
                                     opts['filename'], opts['project'], opts['version'],
                                     opts['library'], opts['encoding'], user.username)
    payload = projects.job_payload(get_project(new_id))
    projects.submit(new_id)
    return ok(payload, request)


def ready_result(job_id: str) -> dict:
    if get_project(job_id).status != 'done':
        raise KbError('40901', '任务尚未完成')
    return projects.load_result(job_id)


@router.get('/{job_id}/chunks')
def chunks(job_id: str, request: Request, path: str = '', page: int = Query(1, ge=1),
           page_size: int = Query(20, ge=1, le=100), user: User = Depends(current_user)):
    rows = ready_result(job_id)['chunks']
    if path:
        rows = [r for r in rows if r['path'] == path]
    return ok(dict(total=len(rows), items=rows[(page-1)*page_size:page*page_size]), request)


@router.get('/{job_id}/graph')
def graph(job_id: str, request: Request, path: str = '', user: User = Depends(current_user)):
    result = ready_result(job_id)
    nodes, edges = result['nodes'], result['edges']
    if path:
        selected = {n['id'] for n in nodes if n['props']['path'] == path}
        adjacent = [e for e in edges if e['src'] in selected or e['dst'] in selected]
        selected |= {e['src'] for e in adjacent} | {e['dst'] for e in adjacent}
        nodes = [n for n in nodes if n['id'] in selected]
    total = len(nodes)
    nodes = nodes[:500]
    ids = {n['id'] for n in nodes}
    filtered = [e for e in edges if e['src'] in ids and e['dst'] in ids]
    return ok(dict(nodes=nodes, edges=filtered[:1500], total=total,
                   truncated=total > 500 or len(filtered) > 1500), request)


@router.get('/{job_id}/source')
def source(job_id: str, request: Request, path: str, user: User = Depends(current_user)):
    job = get_project(job_id)
    if path not in job.options_json['files']:
        raise KbError('40401', '工程中不存在该文件')
    content = (projects.snapshot_root(job_id) / 'source' / path).read_text('utf-8')
    return ok(dict(path=path, content=content, lines=len(content.splitlines())), request)
