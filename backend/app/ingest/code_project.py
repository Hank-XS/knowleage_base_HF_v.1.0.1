"""Offline, versioned COBOL project ingestion. CodeGraph is the only structural parser.

Each upload is an immutable snapshot. A single worker publishes snapshots in order;
failed parsing never replaces the last successful snapshot of the same version.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from ..config import BASE_DIR
from ..db import IngestJob, KbDocChunk, KbDocument, KbDocVersion, KbLibrary, SessionLocal
from ..llm import HashEmbedder
from ..stores.graph import graph_store
from ..stores.objects import object_store
from ..stores.vector import vector_store

MAX_UPLOAD = 50 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_SOURCE = 1024 * 1024
MAX_FILES = 5000
EXTENSIONS = {'.cbl', '.cob', '.cobol', '.cpy'}
IGNORED = {'.git', '.codegraph', 'node_modules', '__macosx'}
STEP_NAMES = ['extract', 'parse', 'chunk', 'publish']
worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='code-project')


def snapshot_root(job_id: str) -> Path:
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('无效任务编号')
    return object_store._root / 'kb-raw' / 'projects' / job_id


def inspect_archive(content: bytes, encoding: str = 'utf-8') -> tuple[dict[str, str], list[dict]]:
    """Validate BEFORE writing. Never extract archive-provided config or executables."""
    if encoding not in {'utf-8', 'gb18030'}:
        raise ValueError('源码编码只支持 UTF-8 或 GB18030')
    if len(content) > MAX_UPLOAD:
        raise ValueError('ZIP 不能超过 50 MB')
    sources, skipped, seen = {}, [], set()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                raise ValueError('ZIP 条目不能超过 5000 个')
            if sum(e.file_size for e in entries) > MAX_EXPANDED:
                raise ValueError('ZIP 解压总量不能超过 200 MB')
            for entry in entries:
                name = entry.filename.replace('\\', '/')
                p = PurePosixPath(name)
                if (p.is_absolute() or '..' in p.parts or not p.parts
                        or any(':' in s or s.endswith((' ', '.')) or
                               re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', s)
                               for s in p.parts)
                        or any(ord(c) < 32 for c in name) or len(name) > 240):
                    raise ValueError(f'ZIP 含不安全路径：{name[:100]}')
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ValueError('不支持符号链接或加密 ZIP')
                normalized = p.as_posix()
                if normalized.casefold() in seen:
                    raise ValueError(f'ZIP 存在重复或大小写冲突路径：{normalized}')
                seen.add(normalized.casefold())
                if entry.is_dir():
                    continue
                if len(p.parts) > 20:
                    raise ValueError('目录深度不能超过 20 层')
                if any(s.lower() in IGNORED for s in p.parts) or p.suffix.lower() not in EXTENSIONS:
                    skipped.append({'path': normalized, 'reason': '首版仅解析 COBOL / Copybook，其他文件保留在原始 ZIP 中'})
                    continue
                if entry.file_size > MAX_SOURCE:
                    raise ValueError(f'{normalized} 超过单个源码文件 1 MB 限制')
                raw = archive.read(entry)
                try:
                    source = raw.decode('utf-8-sig' if encoding == 'utf-8' else encoding)
                except UnicodeDecodeError as exc:
                    raise ValueError(f'{normalized} 不是所选编码，请检查源码编码') from exc
                if '\x00' in source:
                    raise ValueError(f'{normalized} 包含二进制内容')
                if len(source.encode('utf-8')) > MAX_SOURCE:
                    raise ValueError(f'{normalized} 转为 UTF-8 后超过 1 MB')
                sources[normalized] = source
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ValueError('ZIP 损坏或使用了不支持的压缩方式') from exc
    if not sources:
        raise ValueError('ZIP 中未找到 .cbl / .cob / .cobol / .cpy 文件')
    return sources, skipped


def create_project(content: bytes, filename: str, project: str, version: str,
                   library: str, encoding: str, author: str) -> str:
    project, version, library = project.strip(), version.strip(), library.strip() or 'code-projects'
    if not project or len(project) > 100 or not version or len(version) > 32 or len(library) > 128:
        raise ValueError('工程名称必填（≤100字符），版本必填（≤32字符）')
    sources, skipped = inspect_archive(content, encoding)
    job_id = uuid.uuid4().hex
    root = snapshot_root(job_id)
    root.mkdir(parents=True)
    (root / 'upload.zip').write_bytes(content)
    for relative, source in sources.items():
        path = root / 'source' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode('utf-8'))
    scope = hashlib.sha256(f'{library}\0{project}\0{version}'.encode()).hexdigest()
    options = dict(project=project, version=version, library=library, encoding=encoding,
                   author=author, filename=Path(filename).name, scope=scope, active=False,
                   files=list(sources), skipped=skipped, engine='CodeGraph', model_used=False)
    with SessionLocal() as db:
        db.add(IngestJob(id=job_id, source_type='code_project', status='queued',
                        object_keys=[f'kb-raw/projects/{job_id}/upload.zip'], options_json=options,
                        steps=[dict(step=s, status='pending', detail='') for s in STEP_NAMES]))
        db.commit()
    return job_id


def submit(job_id: str) -> None:
    worker.submit(run_project, job_id)


def job_payload(job: IngestJob) -> dict:
    return dict(job_id=job.id, status=job.status, error=job.error, steps=job.steps,
                created_at=job.created_at.isoformat(), **job.options_json)


def load_result(job_id: str) -> dict:
    path = snapshot_root(job_id) / 'result.json'
    if not path.is_file():
        raise ValueError('解析结果尚未生成')
    return json.loads(path.read_text('utf-8'))


def run_codegraph(root: Path) -> dict:
    bridge = BASE_DIR / 'tools' / 'codegraph' / 'index-project.cjs'
    node = os.environ.get('KB_CODEGRAPH_NODE') or shutil.which('node')
    bundled_node = bridge.parent / 'node_modules/@colbymchenry/codegraph-win32-x64/node.exe'
    # Desktop local setup also works when uvicorn was started without the Node PATH.
    local_node = BASE_DIR.parents[1] / '.local-tools/node_modules/node-win-x64/bin/node.exe'
    if not os.environ.get('KB_CODEGRAPH_NODE') and local_node.exists():
        node = str(local_node)
    if not os.environ.get('KB_CODEGRAPH_NODE') and os.name == 'nt' and bundled_node.exists():
        node = str(bundled_node)
    if not node:
        raise ValueError('未找到 Node.js，请安装 Node 22.5+ 并设置 KB_CODEGRAPH_NODE')
    log = root / 'codegraph.log'
    with log.open('w', encoding='utf-8') as output:
        try:
            result = subprocess.run([node, '--liftoff-only', str(bridge), str(root / 'source')],
                                    cwd=bridge.parent, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=600, shell=False,
                                    env={**os.environ, 'CODEGRAPH_TELEMETRY': '0', 'DO_NOT_TRACK': '1'})
        except subprocess.TimeoutExpired as exc:
            raise ValueError('CodeGraph 解析超过 10 分钟，请缩小工程后重试') from exc
    if result.returncode:
        tail = log.read_text('utf-8', errors='replace')[-1200:]
        raise ValueError(f'CodeGraph 执行失败，请检查依赖安装。{tail}')
    database = root / 'source' / '.codegraph' / 'codegraph.db'
    if not database.exists():
        raise ValueError('CodeGraph 未生成索引数据库')
    with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return {table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')]
                for table in ('nodes', 'edges', 'files', 'unresolved_refs')}


def adapt_graph(raw: dict, root: Path, options: dict, job_id: str) -> dict:
    files = set(options['files'])
    prefix = f'project/{job_id}/'
    nodes, chunks = [], []
    by_original = {}
    common = dict(project=options['project'], version=options['version'],
                  project_job=job_id, scope=options['scope'], engine='codegraph')
    texts = {p: (root / 'source' / p).read_text('utf-8') for p in files}

    def relative(value: str) -> str:
        path = Path(value)
        return (path.relative_to(root / 'source').as_posix() if path.is_absolute()
                else value.replace('\\', '/'))

    labels = {'module': 'CodeUnit', 'function': 'CodeUnit', 'file': 'CodeFile',
              'variable': 'Field', 'field': 'Field', 'constant': 'Field', 'import': 'CopyBook'}
    for n in raw['nodes']:
        path = relative(n['file_path'])
        if path not in files:
            continue
        lines = texts[path].splitlines(keepends=True)
        start, end = max(1, n['start_line']), min(len(lines), n['end_line'])
        if start > end:
            continue
        nid = prefix + n['id']
        props = {**common, 'name': n['name'], 'kind': n['kind'], 'path': path,
                 'source_path': f'kb-raw/projects/{job_id}/source/{path}',
                 'start_line': start, 'end_line': end, 'loc': f'L{start}-L{end}'}
        node = dict(id=nid, label=labels.get(n['kind'], 'CodeUnit'), props=props)
        nodes.append(node)
        by_original[n['id']] = node
        # Structural units, with bounded line-preserving subdivisions for large sections.
        if n['kind'] in {'function', 'variable', 'constant'}:
            for first in range(start, end + 1, 100):
                last = min(first + 99, end)
                chunks.append(dict(id=hashlib.sha256(f'{nid}:{first}'.encode()).hexdigest()[:32],
                                   node_id=nid, path=path, title=n['name'], start_line=first, end_line=last,
                                   text=''.join(lines[first - 1:last]),
                                   start_offset=sum(map(len, lines[:first - 1])),
                                   end_offset=sum(map(len, lines[:last]))))
    # Files with no recognized paragraph/data item remain readable and searchable;
    # fallback is explicit and must not claim a structural parse succeeded.
    covered = {ch['path'] for ch in chunks}
    for path in files - covered:
        lines = texts[path].splitlines(keepends=True)
        for first in range(1, len(lines) + 1, 100):
            last = min(first + 99, len(lines))
            chunks.append(dict(id=hashlib.sha256(f'{prefix}{path}:{first}'.encode()).hexdigest()[:32],
                               node_id='', path=path, title=f'{Path(path).name}（文件切片）',
                               start_line=first, end_line=last, text=''.join(lines[first - 1:last]),
                               start_offset=sum(map(len, lines[:first - 1])), end_offset=sum(map(len, lines[:last]))))
    edges = []
    for e in raw['edges']:
        if e['source'] in by_original and e['target'] in by_original:
            edges.append(dict(src=prefix + e['source'], dst=prefix + e['target'],
                              rel=e['kind'].upper(), props={**common, 'line': e.get('line') or 0,
                                                          'metadata': e.get('metadata') or ''}))
    unresolved = []
    for ref in raw['unresolved_refs']:
        origin = by_original.get(ref['from_node_id'])
        unresolved.append(dict(name=ref['reference_name'], kind=ref['reference_kind'],
                               path=origin['props']['path'] if origin else ref.get('file_path', ''),
                               line=ref['line']))
    indexed = {relative(f['path']): f for f in raw['files']}
    report_files = [dict(path=p, indexed=p in indexed,
                         errors=indexed.get(p, {}).get('errors') or '',
                         structural_chunks=p in covered,
                         chunks=sum(ch['path'] == p for ch in chunks)) for p in sorted(files)]
    if not any(n['props']['kind'] in {'module', 'function', 'variable', 'field'} for n in nodes):
        raise ValueError('CodeGraph 未提取到 COBOL 结构；请检查版本、格式和源码编码')
    return dict(nodes=nodes, edges=edges, chunks=chunks, files=report_files, unresolved=unresolved,
                summary=dict(files=len(files), nodes=len(nodes), edges=len(edges), chunks=len(chunks),
                             unresolved=len(unresolved), skipped=len(options['skipped']),
                             warnings=sum(not f['indexed'] or bool(f['errors'] and f['errors'] != '[]')
                                          or not f['structural_chunks'] for f in report_files)),
                embedding='hash:ngram（本地基础检索，非语义模型）', engine_version='1.6.2')


def _remove_snapshot(job_id: str) -> None:
    graph_store.delete_by_meta('project_job', job_id)
    vector_store.delete_by_meta('kb_code_chunk', 'project_job', job_id)


def publish(job_id: str, result: dict, options: dict) -> None:
    root = snapshot_root(job_id)
    common = dict(project_job=job_id, project=options['project'], version=options['version'],
                  scope=options['scope'], lang='COBOL', kb_version=options['version'], tier='B', trust=0.85)
    embedder = HashEmbedder()
    with SessionLocal() as db:
        previous_ids = [j.id for j in db.scalars(select(IngestJob).where(
            IngestJob.source_type == 'code_project', IngestJob.id != job_id))
            if j.options_json.get('scope') == options['scope'] and j.options_json.get('active')]
    # Preserve just the snapshots we may replace; unrelated knowledge is never rolled back.
    old_nodes = [n for n in graph_store.dump()['nodes'] if n['props'].get('project_job') in previous_ids]
    old_ids = {n['id'] for n in old_nodes}
    old_edges = [e for e in graph_store.dump()['edges'] if e['src'] in old_ids or e['dst'] in old_ids]
    old_vectors = [c for c in vector_store._data['kb_code_chunk']
                   if c['meta'].get('project_job') in previous_ids]
    try:
        for node in result['nodes']:
            graph_store.upsert_node(node['id'], node['label'], node['props'])
        for edge in result['edges']:
            graph_store.upsert_edge(edge['src'], edge['rel'], edge['dst'], edge['props'])
        for ch in result['chunks']:
            meta = {**common, 'text': ch['text'], 'code_unit': ch['title'], 'title': ch['title'],
                    'obj': ch['node_id'], 'source_path': f'kb-raw/projects/{job_id}/source/{ch["path"]}',
                    'loc': f'L{ch["start_line"]}-L{ch["end_line"]}', 'embedding': embedder.name}
            vector_store.upsert('kb_code_chunk', ch['id'], embedder.embed([ch['text']])[0], meta)
        with SessionLocal() as db:
            if not db.get(KbLibrary, options['library']):
                db.add(KbLibrary(key=options['library'], title=options['library']))
            for file in result['files']:
                path = file['path']
                key = f'kb-raw/projects/{job_id}/source/{path}'
                text = (root / 'source' / path).read_text('utf-8')
                doc = KbDocument(library_key=options['library'], path=key, source_path=key, object_key=key,
                                 name=f'{options["project"]}/{path}'[:256], doc_type=Path(path).suffix[1:],
                                 version=options['version'], status='published', vectorized=1, official=0,
                                 author=options['author'], size_bytes=len(text.encode()), tags_json=['COBOL', 'CodeGraph'])
                db.add(doc)
                db.flush()
                db.add(KbDocVersion(doc_id=doc.id, version=options['version'], content=text,
                                    created_by=options['author']))
                for i, ch in enumerate(c for c in result['chunks'] if c['path'] == path):
                    db.add(KbDocChunk(id=ch['id'], doc_id=doc.id, version=options['version'], chunk_index=i,
                                     title=ch['title'][:256], text=ch['text'],
                                     start_offset=ch['start_offset'], end_offset=ch['end_offset']))
            # Only replace the SAME project/version. Other versions remain independent.
            for previous_id in previous_ids:
                _remove_snapshot(previous_id)
                previous = db.get(IngestJob, previous_id)
                previous.options_json = {**previous.options_json, 'active': False, 'superseded_by': job_id}
                old_docs = db.scalars(select(KbDocument).where(
                    KbDocument.source_path.startswith(f'kb-raw/projects/{previous_id}/source/'))).all()
                for doc in old_docs:
                    doc.status = 'archived'
                    doc.vectorized = 0
            current = db.get(IngestJob, job_id)
            current.options_json = {**current.options_json, 'active': True, 'summary': result['summary']}
            current.status = 'done'
            current.steps = [{**s, **(dict(status='done', detail='处理完成；可查看源码、切片和图谱')
                                     if s['step'] == 'publish' else {})} for s in current.steps]
            graph_store.save()
            vector_store.save()
            db.commit()
    except Exception:
        _remove_snapshot(job_id)
        for node in old_nodes:
            graph_store.upsert_node(node['id'], node['label'], node['props'])
        for edge in old_edges:
            graph_store.upsert_edge(edge['src'], edge['rel'], edge['dst'], edge['props'])
        for chunk in old_vectors:
            vector_store.upsert('kb_code_chunk', chunk['id'], chunk['vector'], chunk['meta'])
        graph_store.save()
        vector_store.save()
        raise


def run_project(job_id: str) -> None:
    def update(step: str, step_status: str, detail: str = '', **values) -> None:
        with SessionLocal() as db:
            job = db.get(IngestJob, job_id)
            job.steps = [{**s, **(dict(status=step_status, detail=detail) if s['step'] == step else {})}
                         for s in job.steps]
            for key, value in values.items():
                setattr(job, key, value)
            db.commit()
    current_step = 'extract'
    try:
        with SessionLocal() as db:
            options = dict(db.get(IngestJob, job_id).options_json)
        root = snapshot_root(job_id)
        update('extract', 'done', f'{len(options["files"])} 个源码文件，跳过 {len(options["skipped"])} 个文件', status='running')
        current_step = 'parse'
        update(current_step, 'running', 'CodeGraph 正在解析完整工程')
        raw = run_codegraph(root)
        update(current_step, 'done', f'{len(raw["nodes"])} 个结构节点')
        current_step = 'chunk'
        update(current_step, 'running')
        result = adapt_graph(raw, root, options, job_id)
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
        update(current_step, 'done', f'{len(result["chunks"])} 个切片，{len(result["unresolved"])} 个未解析引用')
        current_step = 'publish'
        update(current_step, 'running', '保存源码、切片、图谱和本地检索索引')
        publish(job_id, result, options)
    except Exception as exc:
        update(current_step, 'failed', str(exc)[:1800], status='failed', error=str(exc)[:1800])


def recover_interrupted() -> None:
    """Local worker is not a durable queue. Expose interrupted jobs for explicit retry."""
    with SessionLocal() as db:
        for job in db.scalars(select(IngestJob).where(IngestJob.source_type == 'code_project',
                                                     IngestJob.status.in_(['queued', 'running']))):
            job.status = 'failed'
            job.error = '服务重启中断了任务，请点击重试'
            job.steps = [{**s, 'status': 'failed' if s['status'] == 'running' else s['status']} for s in job.steps]
        db.commit()
