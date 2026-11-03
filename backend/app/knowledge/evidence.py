"""Evidence identity, exact line spans and stable citations shared by both QA paths."""
from __future__ import annotations

import re
from pathlib import PurePosixPath


CODE_TYPES = {'code', 'cobol', 'cbl', 'cob', 'cpy', 'copybook'}


def normalize(item: dict, default_channel='doc') -> dict:
    e = dict(item)
    channel = e.get('channel') or e.get('type') or default_channel
    path = str(e.get('path') or e.get('obj') or '').replace('\\', '/')
    if not path and '/' in str(e.get('label', '')):
        path = e['label'].replace('\\', '/')
    if channel in CODE_TYPES or (channel == 'doc' and PurePosixPath(path).suffix.lower() in {'.cbl', '.cob', '.cpy'}):
        channel = 'code'
    if channel == 'graph':
        path = e.get('graph_id') or path
    e.update(channel=channel, path=path, obj=path, text=e.get('text') or e.get('snippet') or '',
             loc=e.get('loc') or '', ref=e.get('ref') or e.get('title') or PurePosixPath(path).name)
    return e


def span(e):
    match = re.fullmatch(r'L(\d+)(?:-L?(\d+))?', e.get('loc', '').strip())
    return (int(match[1]), int(match[2] or match[1])) if match else None


def identity(e):
    # Object paths identify uploaded versions; legacy paths also need explicit version metadata.
    if e.get('path', '').startswith('kb-raw/projects/'):
        return e.get('channel'), e['path']
    return e.get('channel'), e.get('path'), e.get('version', ''), e.get('library', ''), e.get('project', '')


def duplicate(a, b):
    if identity(a) != identity(b):
        return False
    if not a.get('path'):
        return a.get('ref') == b.get('ref') and a.get('text') == b.get('text')
    if a.get('channel') == 'graph':
        return a.get('ref') == b.get('ref')
    sa, sb = span(a), span(b)
    if sa and sb:
        overlap = min(sa[1], sb[1]) - max(sa[0], sb[0]) + 1
        return overlap > 0 and overlap / min(sa[1] - sa[0] + 1, sb[1] - sb[0] + 1) >= .8
    return bool(a.get('text')) and re.sub(r'\s+', ' ', a['text']).strip() == re.sub(r'\s+', ' ', b['text']).strip()


def merge_spans(a, b):
    """Merge only verifiable, consistent original lines. Never invent omitted lines."""
    sa, sb = span(a), span(b)
    if not sa or not sb:
        return None
    begin, end = min(sa[0], sb[0]), max(sa[1], sb[1])
    if end - begin >= 80:
        return None
    lines = {}
    for e, bounds in ((a, sa), (b, sb)):
        original = e['text'].splitlines(keepends=True)
        if len(original) != bounds[1] - bounds[0] + 1:
            return None  # Truncated snippets must not claim complete line coverage.
        for no, line in enumerate(original, bounds[0]):
            if no in lines and lines[no].rstrip('\r\n') != line.rstrip('\r\n'):
                return None
            lines[no] = line
    if len(lines) != end - begin + 1:
        return None
    return {**a, 'text': ''.join(lines[n].rstrip('\r\n') + '\n' for n in range(begin, end + 1)), 'loc': f'L{begin}-L{end}'}


class EvidenceRegistry:
    """Numbers are assigned before the model sees a passage and never move afterwards."""
    def __init__(self, items=None):
        self.items = items if items is not None else []
        self.items[:] = [normalize(item) for item in self.items]

    def add(self, item, default_channel='doc'):
        evidence = normalize(item, default_channel)
        for index, previous in enumerate(self.items):
            if duplicate(previous, evidence):
                merged = merge_spans(previous, evidence)
                if evidence.get('relation_type') == 'exact_source':
                    previous = {**previous, 'relation_type':'exact_source', 'code_similarity':1.0}
                    self.items[index] = previous
                if merged:
                    if previous.get('relation_type') == 'exact_source':
                        merged.update(relation_type='exact_source', code_similarity=1.0)
                    self.items[index] = merged
                elif span(previous) != span(evidence) and previous['text'] != evidence['text']:
                    continue  # Conflicting/truncated ranges remain individually traceable.
                return index + 1
        self.items.append(evidence)
        return len(self.items)

    def sources(self, include_text=False):
        return [dict(no=i, type=e['channel'], ref=e.get('ref') or '', label=e.get('label') or '',
                     kind=e.get('kind', 'chunk'),
                     relation_type=e.get('relation_type', ''),
                     path=e['path'], obj=e['path'], loc=e['loc'], snippet=e['text'][:160],
                     score=e.get('rank_score') or e.get('score') or 0,
                     project=e.get('project', ''), library=e.get('library', ''), version=e.get('version', ''),
                     **({'text': e['text']} if include_text else {}))
                for i, e in enumerate(self.items, 1)]
