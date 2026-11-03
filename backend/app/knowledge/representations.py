"""Parent-preserving children and derived retrieval text. Only original spans are evidence."""
import hashlib
import re

from ..config import settings


def token_count(text, tokenizer=None):
    if tokenizer is not None:
        return len(tokenizer.encode(text, add_special_tokens=False))
    # Conservative fallback for the model-free path; never called an exact token count.
    return len(text.encode('utf-8'))


def behavior(text):
    operations = [('READ', '读取文件记录'), ('WRITE', '写入文件记录'), ('CALL', '调用外部程序'),
                  ('PERFORM', '执行段落或循环'), ('COMPUTE', '计算表达式'), ('IF', '条件判断'),
                  ('MOVE', '赋值'), ('ADD', '累加'), ('SUBTRACT', '扣减'), ('COPY', '引入数据定义')]
    from .lexical import executable_line
    code = '\n'.join(executable_line(line) for line in text.splitlines())
    found = [f'{name}: {label}' for name, label in operations if re.search(r'\b' + name + r'\b', code, re.I)]
    # These are mechanical operations, not inferred business claims or source evidence.
    return '代码操作：' + '；'.join(found) if found else ''


def file_overview(body, source_path):
    lines = body.splitlines(keepends=True)
    center = next((i for i,line in enumerate(lines[:120]) if re.search(r'\b(?:FUNCTION|PURPOSE|DESCRIPTION)\s*[:.]',line,re.I)), 0)
    begin, end = max(0,center-4), min(len(lines),center+8)
    return dict(id='overview-'+hashlib.sha256((source_path+'\0'+body).encode()).hexdigest()[:24],
        text=''.join(lines[begin:end]),loc=f'L{begin+1}-L{end}',title=source_path.rsplit('/',1)[-1])


def children(parent_id, text, metadata, tokenizer=None):
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    match = re.match(r'L(\d+)', metadata.get('loc', ''))
    start_line = int(match[1]) if match else metadata.get('start_line', 1)
    limit = settings.kb_child_tokens
    is_code = metadata.get('channel') == 'code' or bool(re.search(r'\.(?:cbl|cob|cobol|cpy)$', metadata.get('source_path', ''), re.I))
    windows = []
    begin = 0
    while begin < len(lines):
        end = begin
        body = ''
        while end < len(lines) and token_count(body + lines[end], tokenizer) <= limit:
            body += lines[end]; end += 1
        if end == begin:
            # An oversized single line stays original; window below by character offsets.
            value = lines[begin]
            offset = 0
            while offset < len(value):
                last = min(len(value), offset + max(16, limit // 2))
                while last > offset + 1 and token_count(value[offset:last], tokenizer) > limit:
                    last = offset + (last - offset) // 2
                windows.append((begin, begin + 1, value[offset:last], offset, last))
                offset = last
            begin += 1; continue
        # Prefer a blank paragraph/statement boundary without throwing away the current span.
        if end < len(lines):
            boundaries = [i for i in range(begin + 1, end + 1) if not lines[i - 1].strip() or (is_code and re.search(r'(?:END-IF|END-EVALUATE|END-PERFORM|\.)\s*$', lines[i - 1], re.I))]
            if boundaries:
                end = boundaries[-1]; body = ''.join(lines[begin:end])
        windows.append((begin, end, body, 0, None))
        if end >= len(lines):
            break
        overlap = min(2, max(0, (end - begin) // 8))
        begin = max(begin + 1, end - overlap)
    output = []
    for begin, end, body, column, last_column in windows:
        offset = sum(map(len, lines[:begin])) + column
        child_id = hashlib.sha256(f'{parent_id}:{offset}:{body}'.encode()).hexdigest()[:32]
        loc = f'L{start_line + begin}-L{start_line + end - 1}'
        if last_column is not None:
            loc = f'L{start_line + begin}（列{column + 1}-{last_column}节选）'
        title = metadata.get('title') or metadata.get('code_unit') or ''
        context = '\n'.join(p for p in (title, metadata.get('heading', '')) if p)
        raw = f'{context}\n{body}'.strip()
        description = behavior(body) if is_code else ''
        retrieval_text = f'{context}\n{description}\n{body}'.strip()
        output.append(dict(id=child_id, parent_id=parent_id, text=body, loc=loc,
            start_offset=offset, end_offset=offset + len(body), representation='original',
            search_text=retrieval_text, representations=[raw] + ([retrieval_text] if description else []),
            context_partial=len(windows) > 1, tokens=token_count(retrieval_text, tokenizer)))
    return output


def encode_parent(parent_id, text, metadata, embedder):
    return encode_many([(parent_id, text, metadata)], embedder)[0]


def encode_many(parents, embedder):
    prepared = [(parent_id, text, metadata, children(parent_id, text, metadata, getattr(embedder, 'tokenizer', None)))
                for parent_id, text, metadata in parents]
    for _, _, metadata, passages in prepared:
        if overview := metadata.get('file_overview'):
            passages.extend(children(overview['id'],overview['text'],{**metadata,'loc':overview['loc'],
                'title':overview['title']},getattr(embedder,'tokenizer',None)))
    texts = [representation for _, _, _, passages in prepared for child in passages for representation in child['representations']]
    vectors = embedder.embed(texts)
    from ..ingest.quality import validate_embeddings
    validate_embeddings(vectors, len(texts))
    cursor = 0
    output = []
    for parent_id, text, metadata, passages in prepared:
        start = cursor
        for child in passages:
            width = len(child.pop('representations'))
            child['vectors'] = vectors[cursor:cursor + width]; cursor += width
        vector = vectors[start] if cursor > start else []
        output.append((vector, {**{k:v for k,v in metadata.items() if k!='file_overview'}, 'children': passages, 'embedding': embedder.name,
                         'parent_id':parent_id, 'chunker':'parent-child-v1'}))
    return output
