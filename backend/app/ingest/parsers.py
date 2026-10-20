"""离线素材解析器：错误码表 / mapping / 返回报文 / 业务文档 / COBOL 源码。

输出统一为 ParsedBundle：
  nodes: [(node_id, label, props)]
  edges: [(src, rel, dst, props)]
  chunks: [{collection, chunk_id, text, meta}]   —— 向量化入库单元
  tags:   [{node_id, tag: {category, value}, source: ai|rule}]  —— 待治理标签
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import openpyxl


class ParsedBundle(dict):
    @property
    def nodes(self) -> list: return self.setdefault("nodes", [])
    @property
    def edges(self) -> list: return self.setdefault("edges", [])
    @property
    def chunks(self) -> list: return self.setdefault("chunks", [])
    @property
    def tags(self) -> list: return self.setdefault("tags", [])

    def node(self, node_id: str, label: str, props: dict | None = None) -> str:
        self.nodes.append((node_id, label, props or {}))
        return node_id

    def edge(self, src: str, rel: str, dst: str, props: dict | None = None) -> None:
        self.edges.append((src, rel, dst, props or {}))


def _read_table(content: bytes, filename: str) -> list[dict]:
    """csv / xlsx / json 统一读为行字典列表。"""
    name = filename.lower()
    if name.endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        header = [str(h).strip() if h else "" for h in rows[0]]
        return [dict(zip(header, r)) for r in rows[1:] if any(r)]
    if name.endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        return data if isinstance(data, list) else [data]
    text = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


# ------------------------------------------------------------- 错误码表
def parse_error_codes(content: bytes, filename: str, source_path: str) -> ParsedBundle:
    b = ParsedBundle(source_type="error_code_table")
    rows = _read_table(content, filename)
    for i, r in enumerate(rows):
        code = str(r.get("code") or r.get("错误码") or "").strip()
        if not code:
            continue
        meaning = str(r.get("meaning") or r.get("含义") or "").strip()
        action = str(r.get("action") or r.get("处理建议") or "").strip()
        level = str(r.get("level") or r.get("级别") or "").strip()
        process = str(r.get("process") or r.get("所属流程") or "").strip()
        nid = b.node(f"err/{code}", "ErrorCode",
                     {"name": f"错误码{code}", "code": code, "meaning": meaning,
                      "action": action, "level": level})
        if process:
            pid = b.node(f"bp/{process}", "BusinessProcess", {"name": process})
            b.edge(nid, "RAISED_IN", pid)
        b.chunks.append({
            "collection": "kb_doc_chunk", "chunk_id": f"errc/{code}",
            "text": f"错误码 {code}：{meaning}。处理建议：{action}。级别：{level}" + (f"（所属流程：{process}）" if process else ""),
            "meta": {"title": f"错误码{code}", "doc_type": "error_code_table",
                     "source_path": source_path, "loc": f"row:{i+2}", "tags": ["错误码"]},
        })
        b.tags.append({"node_id": nid, "tag": {"category": "业务对象", "value": "错误码"}, "source": "rule"})
        if any(k in meaning for k in ("余额", "资金")):
            b.tags.append({"node_id": nid, "tag": {"category": "功能域", "value": "余额校验"}, "source": "rule"})
    return b


# ------------------------------------------------------------- mapping
def parse_mapping(content: bytes, filename: str, source_path: str) -> ParsedBundle:
    b = ParsedBundle(source_type="mapping")
    rows = _read_table(content, filename)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        src_sys = str(r.get("src_system") or "老系统").strip()
        src_f = str(r.get("src_field") or r.get("源字段") or "").strip()
        dst_sys = str(r.get("dst_system") or "新系统").strip()
        dst_f = str(r.get("dst_field") or r.get("目标字段") or "").strip()
        rule = str(r.get("rule") or r.get("转换规则") or "").strip()
        bkey = str(r.get("business_key") or r.get("业务键") or "default").strip()
        if not src_f or not dst_f:
            continue
        sid = b.node(f"fld/{src_sys}.{src_f}", "Field", {"name": f"{src_sys}.{src_f}", "system": src_sys})
        did = b.node(f"fld/{dst_sys}.{dst_f}", "Field", {"name": f"{dst_sys}.{dst_f}", "system": dst_sys})
        b.edge(did, "MAPPED_FROM", sid, {"rule": rule})
        groups.setdefault(bkey, []).append(
            {"src": f"{src_sys}.{src_f}", "dst": f"{dst_sys}.{dst_f}", "rule": rule})
    for bkey, items in groups.items():
        text = "\n".join(f"{it['src']} -> {it['dst']}（{it['rule'] or '直传'}）" for it in items)
        b.chunks.append({
            "collection": "kb_mapping_chunk", "chunk_id": f"map/{bkey}",
            "text": text, "meta": {"business_key": bkey, "source_path": source_path,
                                   "doc_type": "mapping", "tags": ["字段映射"]},
        })
        b.tags.append({"node_id": f"map/{bkey}", "tag": {"category": "业务对象", "value": "字段映射"}, "source": "rule"})
    return b


# ------------------------------------------------------------- 返回报文
def parse_message_format(content: bytes, filename: str, source_path: str) -> ParsedBundle:
    b = ParsedBundle(source_type="message_format")
    spec = json.loads(content.decode("utf-8"))
    mname = spec.get("name", Path(filename).stem)
    mid = b.node(f"mf/{mname}", "MessageFormat",
                 {"name": mname, "direction": spec.get("direction", "response"), "version": spec.get("version", "v1")})
    fields = spec.get("fields", [])
    for f in fields:
        fid = b.node(f"fld/{mname}.{f['name']}", "Field",
                     {"name": f"{mname}.{f['name']}", "type": f.get("type", "C"),
                      "length": f.get("length", 0), "desc": f.get("desc", "")})
        b.edge(mid, "HAS_FIELD", fid)
    for ifname in spec.get("used_by", []):
        iid = b.node(f"if/{ifname}", "Interface", {"name": ifname, "protocol": spec.get("protocol", "CICS")})
        b.edge(iid, "USES", mid)
    text = "\n".join(f"{f['name']} {f.get('type','')}({f.get('length','')}) {f.get('desc','')}" for f in fields)
    b.chunks.append({
        "collection": "kb_doc_chunk", "chunk_id": f"msg/{mname}",
        "text": f"报文 {mname}（{spec.get('direction','')}）字段：\n{text}",
        "meta": {"title": mname, "doc_type": "message_format", "source_path": source_path, "tags": ["报文"]},
    })
    return b


# ------------------------------------------------------------- 业务文档
def parse_doc(content: bytes, filename: str, source_path: str) -> ParsedBundle:
    b = ParsedBundle(source_type="doc")
    text = content.decode("utf-8", errors="replace")
    # 按标题分节，再按长度切 chunk（512~1024）
    sections = re.split(r"\n(?=#{1,3} )", text)
    idx = 0
    for sec in sections:
        m = re.match(r"#+\s*(.+)", sec)
        title = m.group(1).strip() if m else Path(filename).stem
        body = sec
        for i in range(0, max(len(body), 1), 800):
            piece = body[i:i + 800].strip()
            if not piece:
                continue
            idx += 1
            b.chunks.append({
                "collection": "kb_doc_chunk", "chunk_id": f"doc/{source_path}#{idx}",
                "text": piece,
                "meta": {"title": title, "doc_type": "doc", "source_path": source_path,
                         "loc": f"seg:{idx}", "tags": _doc_tags(piece)},
            })
    # 文档中提到的接口/程序登记为候选实体（弱抽取，交治理）
    for name in set(re.findall(r"\b([A-Z]{2,}[A-Z0-9\-]{2,})\b", text)):
        if len(name) >= 4:
            b.tags.append({"node_id": f"cu/{name}", "tag": {"category": "技术属性", "value": "文档提及"}, "source": "rule"})
    return b


DOC_TAG_RULES = [
    ("功能域", "取款", ("取款", "withdraw")),
    ("功能域", "余额查询", ("余额", "balance")),
    ("功能域", "转账", ("转账", "transfer")),
    ("功能域", "对账", ("对账", "reconcil")),
    ("业务对象", "错误码", ("错误码", "error code")),
    ("业务对象", "报文", ("报文", "message")),
    ("业务对象", "卡种", ("卡种", "借记卡", "贷记卡")),
    ("交易属性", "渠道ATM", ("atm",)),
]


def _doc_tags(text: str) -> list[str]:
    tl = text.lower()
    return [v for _, v, kws in DOC_TAG_RULES if any(k in tl for k in kws)]


# ------------------------------------------------------------- COBOL
def parse_cobol(content: bytes, filename: str, source_path: str) -> ParsedBundle:
    b = ParsedBundle(source_type="cobol")
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()
    prog = Path(filename).stem.upper()
    pid = b.node(f"cu/{prog}", "CodeUnit",
                 {"name": prog, "kind": "program", "lang": "COBOL",
                  "loc": len(lines)})
    comments = [l.strip("* ").strip() for l in lines if l.strip().startswith("*")]
    b.node(f"cu/{prog}", "CodeUnit",
           {"name": prog, "kind": "program", "lang": "COBOL", "loc": len(lines),
            "comment_head": " ".join(comments[:3])[:200]})

    cur_section = None
    section_lines: dict[str, list[str]] = {}

    def _section_comment(name: str) -> str:
        performs = sorted(set(re.findall(r"PERFORM\s+([0-9A-Z\-]+)", "\n".join(section_lines.get(name, [])), re.I)))
        sqls = re.findall(r"FROM\s+([A-Z0-9_]+)", "\n".join(section_lines.get(name, [])), re.I)
        desc = []
        if performs:
            desc.append("调用：" + ", ".join(performs))
        if sqls:
            desc.append("访问表：" + ", ".join(sorted(set(sqls))))
        return "；".join(desc)

    for raw in lines:
        code = raw[6:72].rstrip() if len(raw) > 6 else raw.rstrip()  # 定宽列裁剪
        s = code.strip()
        m = re.match(r"([0-9A-Z][0-9A-Z\-]*)\s+SECTION\b", s, re.I)
        if m:
            cur_section = m.group(1).upper()
            sid = b.node(f"cu/{prog}.{cur_section}", "CodeUnit",
                         {"name": f"{prog}.{cur_section}", "kind": "section", "lang": "COBOL"})
            b.edge(pid, "PART_OF", sid)
            section_lines[cur_section] = []
            continue
        if cur_section:
            section_lines[cur_section].append(s)
            pm = re.search(r"PERFORM\s+([0-9A-Z\-]+)", s, re.I)
            if pm:
                target = pm.group(1).upper()
                b.edge(pid, "CALLS", f"cu/{prog}.{target}")
            for tb in re.findall(r"EXEC SQL.*?(?:FROM|INTO|UPDATE|INSERT\s+INTO)\s+([A-Z0-9_]+)", s, re.I):
                tid = b.node(f"tbl/{tb.upper()}", "DataTable", {"name": tb.upper()})
                b.edge(pid, "READS", tid)
            if "EXEC CICS" in s.upper():
                cid = b.node(f"tc/CICS", "TechComponent", {"name": "CICS", "ctype": "CICS"})
                b.edge(pid, "DEPLOYED_ON", cid)
            cp = re.search(r"COPY\s+([A-Z0-9\-]+)", s, re.I)
            if cp:
                bid = b.node(f"cb/{cp.group(1).upper()}", "CopyBook", {"name": cp.group(1).upper()})
                b.edge(pid, "READS", bid)

    # section 级 chunk（带规则生成的注释）
    for sec, ls in section_lines.items():
        body = "\n".join(ls)
        b.chunks.append({
            "collection": "kb_code_chunk", "chunk_id": f"code/{prog}.{sec}",
            "text": f"* 注释（规则生成）：{_section_comment(sec) or '常规处理段'}\n{body[:1200]}",
            "meta": {"code_unit": f"{prog}.{sec}", "lang": "COBOL",
                     "source_path": source_path, "loc": f"section:{sec}",
                     "title": f"{prog}.{sec}"},
        })
    b.tags.append({"node_id": pid, "tag": {"category": "技术属性", "value": "COBOL程序"}, "source": "rule"})
    if prog.startswith("ATM"):
        b.tags.append({"node_id": pid, "tag": {"category": "交易属性", "value": "渠道ATM"}, "source": "rule"})
    return b


PARSERS = {
    "error_code_table": parse_error_codes,
    "mapping": parse_mapping,
    "message_format": parse_message_format,
    "doc": parse_doc,
    "cobol": parse_cobol,
}


def parse_by_type(source_type: str, content: bytes, filename: str, source_path: str) -> ParsedBundle:
    fn = PARSERS.get(source_type)
    if fn is None:
        raise ValueError(f"不支持的 source_type: {source_type}")
    try:
        return fn(content, filename, source_path)
    except Exception as e:  # 解析失败 → 50005
        raise ValueError(f"素材解析失败（{filename}）：{e}") from e
