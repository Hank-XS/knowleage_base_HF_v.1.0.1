"""Keep transport limits and source locations consistent, including expanded caller evidence."""
import re


def bounded(evidence, max_lines=80, max_chars=12000):
    e = dict(evidence)
    text = e.get('text') or ''
    lines = text.splitlines(keepends=True)
    selected, size = [], 0
    for line in lines[:max_lines]:
        if size + len(line) > max_chars:
            break
        selected.append(line); size += len(line)
    if len(selected) == len(lines):
        return e
    match = re.fullmatch(r'L(\d+)(?:-L?(\d+))?', e.get('loc', ''))
    e['content_truncated'] = True
    if selected:
        e['text'] = ''.join(selected)
        if match:
            e['loc'] = f'L{match[1]}-L{int(match[1]) + len(selected) - 1}'
    else:
        e['text'] = text[:max_chars]
        if match:
            e['loc'] = f'L{match[1]}（行内节选）'
    return e


def pack(evidences, budget=6000):
    """Byte-conservative prompt allocation when the generator tokenizer is unavailable.

    UTF-8 byte count is intentionally conservative, not reported as an exact model token count.
    Preserve whole source lines and let EvidenceRegistry merge before numbering.
    """
    remaining = budget
    output = []
    for original in evidences:
        if remaining < 128:
            break
        evidence = dict(original)
        cost = len((evidence.get('text') or '').encode('utf-8')) + 128
        if cost > remaining:
            lines = (evidence.get('text') or '').splitlines(keepends=True)
            selected = []
            size = 128
            for line in lines:
                if size + len(line.encode('utf-8')) > remaining:
                    break
                selected.append(line);size += len(line.encode('utf-8'))
            if not selected:
                continue
            evidence['text'] = ''.join(selected)
            match = re.match(r'L(\d+)', evidence.get('loc', ''))
            if match:
                evidence['loc'] = f'L{match[1]}-L{int(match[1]) + len(selected) - 1}'
            evidence['content_truncated'] = True
            cost = size
        output.append(evidence); remaining -= cost
    return output


def expand_parents(evidences):
    from sqlalchemy import select
    from .. import db as database
    from ..llm import get_embedder
    from .representations import token_count
    tokenizer = getattr(get_embedder(), 'tokenizer', None) if any(e.get('parent_id') for e in evidences) else None
    output = []
    with database.SessionLocal() as db:
        for item in evidences:
            e = dict(item)
            parent_id = e.get('parent_id')
            parent = db.get(database.KbDocChunk, parent_id) if parent_id else None
            if parent and token_count(parent.text, tokenizer) <= 1200:
                version = db.scalar(select(database.KbDocVersion).where(database.KbDocVersion.doc_id == parent.doc_id,
                    database.KbDocVersion.version == parent.version))
                if version and parent.version == e.get('version'):
                    begin = version.content[:parent.start_offset].count('\n') + 1
                    e.update(text=parent.text, loc=f'L{begin}-L{begin + len(parent.text.splitlines()) - 1}', context_partial=False)
            output.append(e)
    return output
