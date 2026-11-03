"""Bounded source evidence for callers, actual dependencies and explicit document mentions."""
import re
from sqlalchemy import select
from .. import db as database
from . import lexical
from .catalog import current_project_jobs
from .relations import relation_graph


def context_evidence(query, seeds, store):
    graph = relation_graph(store)
    current = current_project_jobs()
    anchors = lexical.identifiers(lexical.current_question(query))
    paths = {e.get('path') or e.get('obj') for e in seeds if e.get('channel') in {'code', 'doc'}}
    outputs = []
    with database.SessionLocal() as db:
        docs = db.scalars(select(database.KbDocument).where(database.KbDocument.is_current == 1,
                                database.KbDocument.vectorized == 1)).all()
        docs = [d for d in docs if not d.project_job or d.project_job in current]
        by_path = {d.source_path: d for d in docs}
        versions = {}
        def content(doc):
            if doc.id not in versions:
                versions[doc.id] = db.scalar(select(database.KbDocVersion).where(database.KbDocVersion.doc_id == doc.id,
                                               database.KbDocVersion.version == doc.version))
            return versions[doc.id].content if versions[doc.id] else ''
        def passage(doc, begin, end, title, kind, relation=None):
            lines = content(doc).splitlines(keepends=True)
            begin, end = max(1, begin), min(len(lines), end)
            if begin > end:
                return
            outputs.append(dict(channel='code' if doc.asset_type == 'code' else 'doc', kind=kind,
                ref=title, label=doc.source_path, obj=doc.source_path, path=doc.source_path,
                loc=f'L{begin}-L{end}', text=''.join(lines[begin - 1:end]), score=.95, recall_score=1/59,
                project=doc.project, library=doc.library_key, version=doc.version,
                context_relation=relation or {}, required_context=kind == 'control_context'))
        # Caller evidence is necessary for execution / continuation / termination claims.
        control = any(word in query.lower() for word in ('终止', '继续', '后续', '条件', '何时', '什么时候', '清零', '初始化', '执行', '调用者', 'caller', 'terminate'))
        for path in paths:
            doc = by_path.get(path)
            if not doc or doc.asset_type != 'code' or not control:
                continue
            body = content(doc); lines = body.splitlines(keepends=True)
            chunks = db.scalars(select(database.KbDocChunk).where(database.KbDocChunk.doc_id == doc.id,
                                      database.KbDocChunk.version == doc.version)).all()
            functions = {n['props']['name']: dict(title=n['props']['name'], start=n['props'].get('start_line', 0), end=n['props'].get('end_line', 0))
                         for n in graph.nodes.values() if n['props'].get('source_path') == path and n['props'].get('kind') == 'function'}
            for chunk in chunks:
                if chunk.meta_json.get('kind') == 'function' or chunk.title in functions:
                    start = chunk.meta_json.get('start_line') or body[:chunk.start_offset].count('\n') + 1
                    end = chunk.meta_json.get('end_line') or start + len(chunk.text.splitlines()) - 1
                    functions[chunk.title] = dict(title=chunk.title, start=start, end=end)
            names = {name for name in functions if name.upper() in anchors}
            # For questions naming just a program, find its relevant branch in retrieved source.
            if not names:
                names = {name for name in functions if any(seed.get('ref') == name for seed in seeds)}
                operations = lexical.actions(query)
                preferred = {name for name in names if any(re.search(r'(?m)^\s*' + re.escape(op) + r'\b',
                             ''.join(lines[functions[name]['start'] - 1:functions[name]['end']]), re.I) for op in operations)}
                names = preferred or names
            for name in sorted(names)[:2]:
                unit = functions[name]
                if 0 < unit['start'] <= unit['end'] and unit['end'] - unit['start'] < 80:
                    passage(doc, unit['start'], unit['end'], name, 'unit_context')
                    unit_text = '\n'.join(lexical.executable_line(line) for line in lines[unit['start'] - 1:unit['end']])
                    callees = set(re.findall(r'\bPERFORM\s+([A-Z0-9][A-Z0-9_-]*)', unit_text, re.I)) & functions.keys()
                    # Follow short helper chains; do not pull every alternative of a dispatcher.
                    if 0 < len(callees) <= 2:
                        for callee in sorted(callees):
                            helper = functions[callee]
                            if 0 < helper['start'] <= helper['end'] and helper['end'] - helper['start'] < 80:
                                passage(doc, helper['start'], helper['end'], callee, 'callee_context', dict(caller=name))
            pending, visited = list(names), set()
            for name in pending:
                if name in visited or len(outputs) >= 8:
                    continue
                visited.add(name)
                pattern = re.compile(r'\b(?:PERFORM|GO\s+TO)\s+' + re.escape(name) + r'(?![\w-])', re.I)
                for number, line in enumerate(lines, 1):
                    if not pattern.search(lexical.executable_line(line)):
                        continue
                    owner = [c for c in functions.values() if c['start'] <= number <= c['end']]
                    if owner:
                        owner.sort(key=lambda c: c['end'] - c['start'])
                        chunk = owner[0]; begin = chunk['start']; end = chunk['end']
                        if chunk['title'] not in visited:
                            pending.append(chunk['title'])
                    else:
                        begin, end = max(1, number - 15), number + 15
                    if end - begin > 79:
                        begin, end = max(begin, number - 30), min(end, number + 40)
                    passage(doc, begin, end, '调用上下文：' + name, 'control_context', dict(target=name, line=number))
                    if len(outputs) >= 8:
                        break
            # Older catalogs can lack field metadata or chunks: recover level-88 declarations
            # directly from the preserved source, without generating new persistent slices.
            referenced = lexical.identifiers('\n'.join(e['text'] for e in outputs if e['path'] == path))
            declarations = []
            for number, line in enumerate(lines, 1):
                code = line[7:72] if len(line) > 7 and not line[:6].strip(' 0123456789') else line
                match = re.match(r'\s*(\d{1,2})\s+([A-Z0-9_-]+)\b', code, re.I)
                if match and match[2].upper() in referenced and (match[1] == '88' or match[2].upper() in anchors):
                    declarations.append((match[1] != '88', number, match[2]))
            covered = set()
            for _, number, name in sorted(declarations):
                if number in covered:
                    continue
                begin, end = max(1, number - 2), min(len(lines), number + 2)
                covered.update(range(begin, end + 1))
                passage(doc, begin, end, '条件定义：' + name, 'definition_context')
                if len(covered) >= 10:
                    break
        # Real graph links can expand to an independently uploaded project, never mere name similarity.
        owned = {n['id'] for n in graph.nodes.values() if n['props'].get('source_path') in paths}
        subject_names = {n['props'].get('name', '').upper() for n in graph.nodes.values() if n['id'] in owned and
                         (n['props'].get('kind') == 'module' or n['label'] == 'CodeFile')}
        definition_anchors = anchors - subject_names - {'COPYBOOK', 'COPY', 'PIC', 'COBOL', 'SECTION', 'DIVISION'}
        for edge in graph.edges:
            if edge['rel'] not in {'IMPORTS', 'CALLS', 'MENTIONS'}:
                continue
            if edge['src'] in owned:
                other = graph.node(edge['dst'])
            elif edge['dst'] in owned and edge['rel'] == 'MENTIONS':
                other = graph.node(edge['src'])
            else:
                continue
            if not other:
                continue
            props = other['props']
            doc = by_path.get(props.get('source_path')) or next((d for d in docs if d.id == props.get('doc_id')), None)
            if not doc or doc.source_path in paths:
                continue
            needs = (edge['rel'] == 'IMPORTS' and any(w in query.lower() for w in ('copy', '定义', '字段', 'pic', '小数')) or
                     edge['rel'] == 'CALLS' and any(w in query for w in ('调用', '关系', '影响', '实现')) or edge['rel'] == 'MENTIONS')
            if needs:
                if edge['rel'] == 'IMPORTS':
                    defines = any(w in query.lower() for w in ('定义', '字段', 'pic', '小数'))
                    if defines and definition_anchors and not definition_anchors & lexical.identifiers(content(doc)):
                        continue
                    source = graph.node(edge['src'])
                    source_doc = by_path.get((source or {}).get('props', {}).get('source_path'))
                    if source_doc:
                        from pathlib import PurePosixPath
                        symbol = PurePosixPath(doc.source_path).stem
                        for number, line in enumerate(content(source_doc).splitlines(), 1):
                            if re.search(r'\bCOPY\s+[\"\']?' + re.escape(symbol) + r'(?![\w-])', line, re.I) and not (len(line) > 6 and line[6] == '*'):
                                passage(source_doc, max(1, number - 2), number + 2, 'Copybook 引入：' + symbol, 'dependency_reference', dict(rel='IMPORTS'))
                                break
                text, begin, end = lexical.focus(query, content(doc), max_lines=30)
                passage(doc, begin, end, other['props'].get('name', doc.name), 'dependency_context',
                        dict(rel=edge['rel'], **edge.get('props', {})))
            if len(outputs) >= 8:
                break
    return outputs
