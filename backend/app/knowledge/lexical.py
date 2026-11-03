"""Local BM25 and identifier boundaries. No model, service or persisted slices required."""
from collections import Counter, defaultdict
import math
from pathlib import PurePosixPath
import re
from threading import RLock
from weakref import WeakKeyDictionary


def identifiers(text):
    return {word.upper() for word in re.findall(r'[A-Za-z0-9][A-Za-z0-9_-]*(?:\.(?:cbl|cob|cpy))?', text, re.I)
            if re.search('[A-Za-z]', word)}


def terms(text):
    words = [word.lower() for word in identifiers_list(text)]
    for part in re.findall(r'[\u4e00-\u9fff]+', text):
        words.extend(part[i:i + 2] for i in range(len(part) - 1))
    return words


def identifiers_list(text):
    return re.findall(r'[A-Za-z0-9][A-Za-z0-9_-]*', text)


def current_question(query):
    return query.split('（相关实体：', 1)[0].split('（承接上文问题：', 1)[0]


def executable_line(line):
    """For control-flow lookup only: ignore comments, sequence columns and quoted examples."""
    fixed = len(line) > 7 and not line[:6].strip(' 0123456789')
    if fixed and line[6] in '*/':
        return ''
    code = line[7:72] if fixed else line
    code = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", lambda m: ' ' * len(m[0]), code)
    return code.split('*>', 1)[0]


def actions(query):
    query = current_question(query).lower()
    groups = []
    if any(word in query for word in ('读取', '读文件', 'read ')):
        groups += ['READ']
    if any(word in query for word in ('调用', '外部程序', 'call', '传参', '参数变量')):
        groups += ['CALL', 'USING']
    if any(word in query for word in ('计算', '公式', 'compute', '累计', '累加')):
        groups += ['COMPUTE', 'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE']
    if any(word in query for word in ('是否', '实现', '未实现', '待实现')):
        groups += ['TO BE IMPLEMENTED', 'TODO', 'EXIT', 'CONTINUE']
    return groups


def overview(query):
    q = current_question(query).lower()
    return not actions(query) and any(word in q for word in ('功能', '用途', '作用', '做什么', '干什么', 'purpose', 'overview'))


def focus(query, text, start_line=1, max_lines=14):
    """Return an exact original span around the best instruction, not a head truncation."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return '', start_line, start_line
    query_ids = identifiers(current_question(query))
    operations = actions(query)
    scores = []
    for line in lines:
        code = line[7:72] if len(line) > 7 and not line[:6].strip(' 0123456789') else line
        # Fixed-format and free-format comments cannot prove an executable CALL/COMPUTE.
        comment = (len(line) > 6 and not line[:6].strip(' 0123456789') and line[6] in '*/') or code.lstrip().startswith('*>')
        active = code.split('*>', 1)[0].upper() if not comment else ''
        score = sum(5 for op in operations if re.search(r'(?<![\w-])' + re.escape(op) + r'(?![\w-])', active))
        if comment and any(op in code.upper() for op in ('TO BE IMPLEMENTED', 'TODO')) and 'TODO' in operations:
            score += 6
        score += len(query_ids & identifiers(code))
        if overview(query) and comment and re.search(r'\b(?:FUNCTION|PURPOSE|DESCRIPTION)\s*[:.]', code, re.I):
            score += 10
        scores.append(score)
    center = max(range(len(lines)), key=lambda i: scores[i])
    begin = max(0, center - 4); end = min(len(lines), begin + max_lines)
    if len(lines) <= max_lines:
        begin, end = 0, len(lines)
    return ''.join(lines[begin:end]), start_line + begin, start_line + end - 1


class BM25:
    def __init__(self, rows):
        self.rows = rows; self.postings = defaultdict(list); self.lengths = []
        for index, row in enumerate(rows):
            meta = row['meta']; title = meta.get('title') or meta.get('code_unit') or ''
            filename = PurePosixPath(meta.get('source_path', '').replace('\\', '/')).stem
            tokens = terms((title + ' ') * 3 + (filename + ' ') * 3 + (meta.get('search_text') or meta.get('text', '')))
            self.lengths.append(len(tokens))
            for token, count in Counter(tokens).items():
                self.postings[token].append((index, count))
        self.average = sum(self.lengths) / max(1, len(rows)) or 1

    def search(self, query, limit=30):
        scores = defaultdict(float); count = len(self.rows)
        for token in set(terms(query)):
            matches = self.postings.get(token, [])
            weight = math.log(1 + (count - len(matches) + .5) / (len(matches) + .5))
            for index, frequency in matches:
                norm = 1.2 * (.25 + .75 * self.lengths[index] / self.average)
                scores[index] += weight * frequency * 2.2 / (frequency + norm)
        return [(self.rows[index], score) for index, score in sorted(scores.items(), key=lambda pair: -pair[1])[:limit]]


_indexes = WeakKeyDictionary()
_lock = RLock()


def index_for(store, collection, current_jobs, denied_paths=None):
    with _lock:
        key = store.revision, tuple(sorted(current_jobs)), tuple(sorted(denied_paths or []))
        cached = _indexes.get(store, {}).get(collection)
        if cached and cached[0] == key:
            return cached[1]
        revision, rows = store.metadata_snapshot(collection)
        rows = [row for row in rows if not row['meta'].get('project_job') or row['meta']['project_job'] in current_jobs]
        rows = [row for row in rows if row['meta'].get('source_path', '') not in (denied_paths or set())]
        index = BM25(rows)
        _indexes.setdefault(store, {})[collection] = ((revision, key[1], key[2]), index)
        return index
