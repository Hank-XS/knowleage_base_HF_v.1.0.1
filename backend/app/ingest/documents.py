"""Structure-aware document extraction. Offsets address the normalized reading text."""
from __future__ import annotations

from collections import Counter
import io
from pathlib import Path
import re
import zipfile

MAX_DOCUMENT = 25 * 1024 * 1024
PURPOSES = {'requirements': '需求说明', 'design': '设计说明', 'interface': '接口规范',
            'operations': '操作手册', 'business': '业务规则', 'reference': '参考资料'}


def normalize_tags(tags):
    result, seen = [], set()
    if not isinstance(tags, list):
        raise ValueError('标签必须是列表')
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError('标签必须是文本')
        tag = re.sub(r'\s+', ' ', tag).strip()
        if not tag:
            continue
        if len(tag) > 32:
            raise ValueError('单个标签不能超过 32 个字符')
        if tag.casefold() not in seen:
            result.append(tag)
            seen.add(tag.casefold())
    if len(result) > 12:
        raise ValueError('最多选择 12 个主题标签')
    return result


def markdown_blocks(text):
    blocks, heading, pending, offset = [], [], [], 0
    fence = None

    def flush():
        if pending:
            first, body, kind = pending[0][0], ''.join(p[1] for p in pending), pending[0][2]
            trimmed = body.strip()
            if trimmed:
                start = first + len(body) - len(body.lstrip())
                blocks.append(dict(text=trimmed, start=start, end=start + len(trimmed),
                                   title=' / '.join(heading) or '正文', kind=kind))
            pending.clear()

    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if fence:
            pending.append((offset, line, 'code'))
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                flush()
                fence = None
        elif marker:
            flush()
            fence = marker.group(1)
            pending.append((offset, line, 'code'))
        else:
            h = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
            setext = re.fullmatch(r'\s{0,3}(={3,}|-{3,})\s*', line)
            if setext and len(pending) == 1 and pending[0][2] == 'paragraph':
                level = 1 if setext.group(1)[0] == '=' else 2
                heading = heading[:level - 1] + [pending[0][1].strip()]
                pending[0] = (pending[0][0], pending[0][1], 'heading')
                pending.append((offset, line, 'heading'))
                flush()
            elif h:
                flush()
                level = len(h.group(1))
                heading = heading[:level - 1] + [h.group(2)]
                pending.append((offset, line, 'heading'))
                flush()
            elif not line.strip():
                flush()
            else:
                kind = 'table' if '|' in line and (line.lstrip().startswith('|') or line.count('|') >= 2) else 'paragraph'
                if pending and pending[0][2] != kind:
                    flush()
                pending.append((offset, line, kind))
        offset += len(line)
    flush()
    return blocks


def chunks_from_blocks(text, blocks, target=1800):
    chunks, group = [], []

    def flush():
        if not group:
            return
        start, end = group[0]['start'], group[-1]['end']
        pages = [b['page'] for b in group if b.get('page')]
        chunks.append(dict(chunk_index=len(chunks), title=group[0]['title'], text=text[start:end],
                           start_offset=start, end_offset=end,
                           meta_json=dict(kind=group[0]['kind'] if len(group) == 1 else 'section',
                                          heading=group[0]['title'], page_start=min(pages) if pages else None,
                                          page_end=max(pages) if pages else None,
                                          block_start=group[0]['index'], block_end=group[-1]['index'])))
        group.clear()

    for index, block in enumerate(blocks, 1):
        block['index'] = index
        if group and (block['title'] != group[0]['title'] or block['kind'] in {'table', 'code'}
                      or block['end'] - group[0]['start'] > target):
            flush()
        group.append(block)
        if block['kind'] in {'table', 'code'}:
            flush()
    flush()
    return chunks


def extract_document(filename, content):
    extension = Path(filename).suffix.lower()
    if extension not in {'.docx', '.pdf', '.md'}:
        raise ValueError('文档资料仅支持 DOCX、文本型 PDF 和 Markdown；代码请上传工程 ZIP')
    if not content or len(content) > MAX_DOCUMENT:
        raise ValueError('文档不能为空，且不能超过 25 MB')
    warnings, blocks = [], []
    if extension == '.md':
        try:
            text = content.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError as exc:
            raise ValueError('Markdown 请使用 UTF-8 编码') from exc
        from .quality import prepare_text
        text, quality = prepare_text(text)
        warnings.extend(quality['warnings'])
        blocks = markdown_blocks(text)
    else:
        elements = []
        try:
            if extension == '.docx':
                from docx import Document
                from docx.table import Table
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                        raise ValueError('DOCX 解压内容过大')
                document = Document(io.BytesIO(content))
                headings = []
                for element in document.iter_inner_content():
                    if isinstance(element, Table):
                        rows = []
                        for row in element.rows:
                            cells, seen = [], set()
                            for cell in row.cells:
                                if cell._tc in seen:
                                    continue
                                seen.add(cell._tc)
                                cells.append(cell.text.replace('|', '\\|').replace('\n', '<br>'))
                            rows.append('| ' + ' | '.join(cells) + ' |')
                        value, kind = '\n'.join(rows), 'table'
                    else:
                        value, kind = element.text.strip(), 'paragraph'
                        style = element.style.name if element.style else ''
                        match = re.search(r'(?:Heading|标题)\s*(\d+)', style, re.I)
                        outline = element._p.xpath('./w:pPr/w:outlineLvl/@w:val')
                        level = int(match.group(1)) if match else int(outline[0]) + 1 if outline else 1 if style == 'Title' else 0
                        if level:
                            headings = headings[:level - 1] + [value]
                            kind = 'heading'
                        elif style.lower().startswith('list'):
                            value = '• ' + value
                    if value:
                        elements.append(dict(text=value, kind=kind, title=' / '.join(headings) or '正文'))
            else:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted:
                    raise ValueError('请先移除 PDF 密码后再上传')
                if len(reader.pages) > 2000:
                    raise ValueError('PDF 不能超过 2000 页')
                pages = [(page.extract_text(extraction_mode='layout') or '').strip() for page in reader.pages]
                if not any(page.strip() for page in pages):
                    raise ValueError('未提取到正文：当前只支持文本型 PDF，扫描件请先进行 OCR')
                edges = Counter(line.strip() for page in pages for line in (page.splitlines()[:1] + page.splitlines()[-1:]) if line.strip())
                repeated = {line for line, count in edges.items() if len(pages) >= 3 and count >= max(3, len(pages) * .6)}
                pdf_heading = '正文'
                for number, page in enumerate(pages, 1):
                    if not page:
                        warnings.append(f'第 {number} 页没有可提取文字，请检查是否为图片页')
                        continue
                    lines = page.splitlines()
                    lines = [line for i, line in enumerate(lines) if not ((i in {0, len(lines) - 1}) and
                             (line.strip() in repeated or re.fullmatch(r'(?:第\s*)?\d+\s*(?:页|/\s*\d+)?', line.strip())))]
                    for value in re.split(r'\n\s*\n', '\n'.join(lines)):
                        if value.strip():
                            value = value.strip()
                            first, _, rest = value.partition('\n')
                            if len(first) < 100 and re.match(r'^(?:第[一二三四五六七八九十百\d]+[章节]|\d+(?:\.\d+)*[.、\s]+\S)', first):
                                pdf_heading = first.strip()
                                elements.append(dict(text=first.strip(), kind='heading', title=pdf_heading, page=number))
                                value = rest.strip()
                            if value:
                                table = sum(bool(re.search(r'\S {3,}\S', line)) for line in value.splitlines()) >= 2
                                elements.append(dict(text=value, kind='table' if table else 'paragraph', title=pdf_heading, page=number))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('文件解析失败，请确认文件格式正确且未损坏') from exc
        text, cursor = '', 0
        for element in elements:
            if text:
                text += '\n\n'
                cursor += 2
            blocks.append({**element, 'start': cursor, 'end': cursor + len(element['text'])})
            text += element['text']
            cursor += len(element['text'])
    if not blocks:
        raise ValueError('文件没有可提取的正文内容')
    from .quality import document_quality
    chunks = chunks_from_blocks(text, blocks)
    quality = document_quality(text, chunks)
    warnings = list(dict.fromkeys([*warnings, *quality['warnings']]))
    return dict(content=text, chunks=chunks, warnings=warnings, quality=quality,
                parser=extension[1:], blocks=len(blocks))
