"""数据集清洗引擎（设计：L0—L4 + 隔离支路）。

能力：
  - 扫描 hf_data（或任意 root）只读源目录；
  - Q/D/C/N 规则：隔离危险内容、版本族对齐、跨宇宙消歧、文本规范化；
  - 产出四件套 + 冲突台账：kg_triples / vector_chunks / quarantine / conflict_ledger + manifest；
  - 可被单文件接入流水线的 clean 步骤复用（内容级隔离检测）。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings

# ---------- 策略常量 ----------
SKIP_DIRS = {".git", "08_cleaned", "__pycache__", ".pytest_cache", "node_modules"}

QUARANTINE_NAME_HINTS: list[tuple[str, str]] = [
    ("FIX_TMP_", "R-Q1"),
    ("PYMAIN.OLD", "R-Q1"),
    ("PYRECON#.BAK", "R-Q1"),
    ("_LANDMINES", "R-Q1"),
    ("DLQ_REPLAY_V2", "R-Q1"),
    ("COMMON.cpy", "R-Q1"),
    ("cps_smoke_deploy.sh", "R-Q2"),
]

QUARANTINE_CONTENT_RES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"P@ssw0rd|client_secret\s*=\s*\S+", re.I), "R-Q2", "敏感密钥形态"),
    (re.compile(r"VIP.?skip.?aml|skip aml|TESTSKIPAML", re.I), "R-Q2", "合规旁路"),
    (re.compile(r"exit 0\s*#.*jenkins green|失败.*exit 0", re.I), "R-Q3", "虚假成功"),
    (re.compile(r"7777-DEAD-CODE|DO NOT USE|dont submit", re.I), "R-Q4", "死代码/禁用"),
]

CONFLICT_CONTENT_RES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"C\.AMOUNT\s*-\s*C\.AMOUNT", re.I), "R-C4", "疑似恒零差逻辑"),
    (re.compile(r"COM-TEST-MODE", re.I), "R-C6", "测试开关引用"),
    (re.compile(r"AH\.MING|2019.*退役", re.I), "R-N1", "失效联系人"),
]

SOURCE_TIER: dict[str, dict[str, Any]] = {
    "02_code_assets/github_cobol": {"tier": "A", "trust": 0.95, "kind": "upstream_code"},
    "07_derived": {"tier": "B", "trust": 0.75, "kind": "derived_from_code"},
    "04_system_metadata": {"tier": "B", "trust": 0.70, "kind": "synthetic_meta"},
    "01_tech_docs": {"tier": "C", "trust": 0.55, "kind": "synthetic_doc"},
    "02_code_assets": {"tier": "C", "trust": 0.50, "kind": "synthetic_code"},
    "03_business_rules": {"tier": "C", "trust": 0.55, "kind": "synthetic_doc"},
}

CODE_EXT = {".cbl", ".cob", ".cpy", ".jcl", ".rpgle", ".rex", ".sql", ".mqsc", ".sh"}
DOC_EXT = {".md", ".yaml", ".yml", ".json", ".jsonl", ".csv", ".mmd", ".txt"}
LOG_NAME_HINTS = ("ops_", "audit_", "runtime_")

PROG_ID_RE = re.compile(r"PROGRAM-ID\.\s*([A-Z0-9][A-Z0-9-]*)", re.I)
CALL_RE = re.compile(
    r"""(?:CALL|LINK\s+PROGRAM|XCTL\s+PROGRAM)\s*\(?\s*['\"]([A-Z0-9][A-Z0-9-]*)['\"]""",
    re.I,
)
TRAN_RE = re.compile(r"WS-TRANID\s+PIC\s+X\(04\)\s+VALUE\s+'([A-Z0-9]{4})'", re.I)
DATASET_RE = re.compile(
    r"(?:DATASET|FILE|ASSIGN\s+TO)\s*\(?\s*['\"]?([A-Z][A-Z0-9.]{2,})['\"]?",
    re.I,
)
FR_RE = re.compile(r"\|\s*(FR-?\d+)\s*\|\s*([^|]+)\|", re.I)
MERMAID_EDGE_RE = re.compile(
    r"([A-Za-z0-9_]+)\s*(?:-->|---|-.->)\s*(?:\|[^|]*\|\s*)?([A-Za-z0-9_]+)"
)

VERSION_SUFFIX_RE = re.compile(r"(\.OLD|\.BAK|_V\d+|V\d+)$", re.I)


@dataclass
class CleanResult:
    root: str
    out_dir: str
    generated_at: str
    stats: dict[str, int] = field(default_factory=dict)
    rule_hits: dict[str, int] = field(default_factory=dict)
    kg_triples: int = 0
    vector_chunks: int = 0
    quarantine: int = 0
    conflicts: int = 0
    notes: list[str] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def default_dataset_root() -> Path:
    cfg = (settings.kb_dataset_root or "").strip()
    if cfg:
        return Path(cfg)
    # backend/app/ingest/clean.py → kb-system/hf_data
    return Path(__file__).resolve().parents[3] / "hf_data"


def classify_source(rel: str) -> dict[str, Any]:
    rel_n = rel.replace("\\", "/")
    for prefix, meta in sorted(SOURCE_TIER.items(), key=lambda x: -len(x[0])):
        if rel_n.startswith(prefix):
            return {**meta, "prefix": prefix}
    return {"tier": "D", "trust": 0.3, "kind": "other", "prefix": ""}


def infer_universe(rel: str, entity: str = "") -> str:
    """按路径与实体名推断业务宇宙，用于跨宇宙消歧（R-C1）。"""
    r = rel.replace("\\", "/").upper()
    e = entity.upper()
    if "CARDDEMO" in r or "CARD_DEMO" in r:
        return "CARDDEMO"
    if "VAULT" in r or e in {"WIREXFR0", "OFACCHK0", "EODPROC0"}:
        return "VAULT"
    if "ZBANK" in r:
        return "ZBANK"
    if "LEDGER" in r:
        return "LEDGER"
    if "07_DERIVED" in r and ("CARD" in r or "VAULT" in r):
        return "CARD"
    # FR-01（短）→ CARD；FR-001（三位及以上）→ CPS
    m = re.match(r"FR-(\d+)$", e)
    if m:
        return "CARD" if len(m.group(1)) <= 2 else "CPS"
    if e.startswith("CO") and "02_CODE_ASSETS/GITHUB" in r:
        return "CARDDEMO"
    if e.startswith("PY") or "CPS" in r or "02_CODE_ASSETS/COBOL" in r:
        return "CPS"
    if "01_TECH" in r or "03_BUSINESS" in r:
        return "CPS"
    return "CPS"


def namespaced(entity: str, universe: str) -> str:
    e = entity_normalize(entity)
    if ":" in e:
        return e
    return f"{universe}:{e}"


def entity_normalize(name: str) -> str:
    n = name.strip().upper()
    n = n.replace(".CBL", "").replace(".COB", "")
    aliases = {
        "PYMAIN2": "PYMAIN",
        "CPS.IN": "CPS.IN.Q",
    }
    return aliases.get(n, n)


def normalize_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return text


def strip_cobol_noise(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    skip_license = False
    for ln in lines:
        u = ln.upper()
        if "LICENSED UNDER THE APACHE" in u or "COPYRIGHT AMAZON" in u:
            skip_license = True
        if skip_license:
            if u.strip().startswith("IDENTIFICATION DIVISION") or u.strip().startswith("PROGRAM-ID"):
                skip_license = False
            else:
                continue
        out.append(ln.rstrip())
    compact, blank = [], 0
    for ln in out:
        if not ln.strip():
            blank += 1
            if blank <= 1:
                compact.append("")
        else:
            blank = 0
            compact.append(ln)
    return "\n".join(compact)


def should_quarantine(path: Path, text: str) -> tuple[str, str] | None:
    """返回 (rule, reason) 或 None。"""
    name = path.name
    full = str(path)
    for hint, rule in QUARANTINE_NAME_HINTS:
        if hint.lower() in name.lower() or hint.lower() in full.lower():
            return rule, f"name_hint:{hint}"
    for rx, rule, label in QUARANTINE_CONTENT_RES:
        if rx.search(text):
            return rule, f"content:{label}"
    return None


def detect_content_conflicts(rel: str, text: str) -> list[dict]:
    hits = []
    for rx, rule, label in CONFLICT_CONTENT_RES:
        m = rx.search(text)
        if not m:
            continue
        start = max(0, m.start() - 40)
        hits.append({
            "conflict_id": f"cf_{hashlib.sha1(f'{rel}:{rule}:{m.start()}'.encode()).hexdigest()[:10]}",
            "rule": rule,
            "subject": label,
            "sides": [{
                "claim": label,
                "path": rel,
                "excerpt": text[start:m.end() + 60].replace("\n", " ")[:200],
            }],
            "suggestion": "标注待人工裁决，默认不自动删除正文",
            "status": "pending",
        })
    return hits


def chunk_code(text: str, path: str, max_chars: int = 3500) -> list[dict]:
    text = strip_cobol_noise(text)
    parts = re.split(
        r"(?=\n\s{0,6}\d{0,6}\s*(?:IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE|"
        r"\d{4}-[A-Z0-9-]+\.|[\w-]+-SECTION\.))",
        "\n" + text,
        flags=re.I,
    )
    chunks, buf = [], ""
    for p in parts:
        if not p.strip():
            continue
        if len(buf) + len(p) > max_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf += p
    if buf.strip():
        chunks.append(buf)
    if not chunks:
        chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    return [
        {
            "chunk_id": hashlib.sha1(f"{path}:{i}:{c[:80]}".encode()).hexdigest()[:16],
            "text": c.strip(),
            "chunk_index": i,
        }
        for i, c in enumerate(chunks)
        if len(c.strip()) > 40
    ]


def chunk_doc(text: str, path: str, max_chars: int = 2000) -> list[dict]:
    blocks = re.split(r"(?=\n#{1,3}\s)", "\n" + text)
    if len(blocks) <= 1:
        blocks = re.split(r"\n\s*\n", text)
    chunks, buf = [], ""
    for b in blocks:
        if len(buf) + len(b) > max_chars and buf:
            chunks.append(buf.strip())
            buf = b
        else:
            buf += "\n" + b
    if buf.strip():
        chunks.append(buf.strip())
    return [
        {
            "chunk_id": hashlib.sha1(f"{path}:{i}:{c[:80]}".encode()).hexdigest()[:16],
            "text": c,
            "chunk_index": i,
        }
        for i, c in enumerate(chunks)
        if len(c) > 40
    ]


def extract_triples(rel: str, text: str, src: dict) -> list[dict]:
    triples: list[dict] = []
    universe = infer_universe(rel)
    pid = PROG_ID_RE.search(text)
    program = pid.group(1).upper() if pid else None
    if program:
        universe = infer_universe(rel, program)
        triples.append({
            "s": namespaced(program, universe), "p": "type", "o": "Program",
            "source": rel, "tier": src["tier"], "trust": src["trust"],
            "universe": universe,
        })
    for m in CALL_RE.finditer(text):
        callee = m.group(1).upper()
        if program and callee != program:
            cu = infer_universe(rel, callee)
            triples.append({
                "s": namespaced(program, universe), "p": "calls",
                "o": namespaced(callee, cu),
                "source": rel, "tier": src["tier"], "trust": src["trust"],
                "universe": universe,
            })
    for m in TRAN_RE.finditer(text):
        if program:
            triples.append({
                "s": namespaced(program, universe), "p": "has_tranid",
                "o": m.group(1).upper(),
                "source": rel, "tier": src["tier"], "trust": src["trust"],
                "universe": universe,
            })
    for m in DATASET_RE.finditer(text):
        ds = m.group(1).upper()
        if program and len(ds) >= 4 and not ds.startswith("PIC"):
            triples.append({
                "s": namespaced(program, universe), "p": "uses_dataset", "o": ds,
                "source": rel, "tier": src["tier"],
                "trust": max(0.3, src["trust"] - 0.15),
                "universe": universe,
            })
    if Path(rel).suffix.lower() in {".md", ".csv"}:
        for m in FR_RE.finditer(text):
            fr_id, desc = m.group(1).upper(), m.group(2).strip()
            fr_u = infer_universe(rel, fr_id)
            fr_ns = namespaced(fr_id, fr_u)
            triples.append({
                "s": fr_ns, "p": "type", "o": "Requirement",
                "source": rel, "tier": src["tier"], "trust": src["trust"],
                "universe": fr_u,
            })
            triples.append({
                "s": fr_ns, "p": "description", "o": desc[:200],
                "source": rel, "tier": src["tier"], "trust": src["trust"],
                "universe": fr_u,
            })
            for tok in re.findall(r"`([A-Z][A-Z0-9]{3,})`", desc, re.I):
                tu = infer_universe(rel, tok.upper())
                triples.append({
                    "s": fr_ns, "p": "implemented_by",
                    "o": namespaced(tok.upper(), tu),
                    "source": rel, "tier": src["tier"],
                    "trust": src["trust"] * 0.9,
                    "universe": fr_u,
                    "pending_review": True,
                })
    return triples


def extract_mermaid_triples(rel: str, text: str, src: dict) -> list[dict]:
    triples = []
    universe = infer_universe(rel)
    for a, b in MERMAID_EDGE_RE.findall(text):
        triples.append({
            "s": namespaced(a, universe), "p": "next_step",
            "o": namespaced(b, universe),
            "source": rel, "tier": src["tier"], "trust": src["trust"],
            "universe": universe,
        })
        triples.append({
            "s": namespaced(a, universe), "p": "step_of", "o": Path(rel).stem,
            "source": rel, "tier": src["tier"], "trust": src["trust"],
            "universe": universe,
        })
    return triples


def extract_coupling_triples(rel: str, data: Any, src: dict) -> list[dict]:
    triples = []
    universe = infer_universe(rel)
    if not isinstance(data, dict):
        return triples
    pairs = data.get("pair_dependencies") or data.get("dependencies") or []
    if isinstance(pairs, list):
        for p in pairs:
            if not isinstance(p, dict):
                continue
            a = p.get("src") or p.get("from") or p.get("a")
            b = p.get("dst") or p.get("to") or p.get("b")
            if not a or not b:
                continue
            w = p.get("freq_30d_avg") or p.get("weight") or p.get("freq") or 1
            triples.append({
                "s": namespaced(str(a), universe), "p": "depends_on",
                "o": namespaced(str(b), universe),
                "source": rel, "tier": src["tier"], "trust": src["trust"],
                "universe": universe, "weight": w,
            })
    modules = data.get("modules") or []
    if isinstance(modules, list):
        for m in modules:
            name = m if isinstance(m, str) else (m.get("name") if isinstance(m, dict) else None)
            if name:
                triples.append({
                    "s": namespaced(str(name), universe), "p": "type", "o": "SubSystem",
                    "source": rel, "tier": src["tier"], "trust": src["trust"],
                    "universe": universe,
                })
    return triples


def extract_log_chunks(rel: str, text: str, src: dict) -> tuple[list[dict], list[dict]]:
    """运维日志 → 按 source/日摘要 chunk + relates_to_txn 三元组。"""
    chunks, triples = [], []
    by_key: dict[str, list[str]] = {}
    universe = infer_universe(rel)
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        src_n = str(ev.get("source") or ev.get("svc") or "unknown")
        ts = str(ev.get("ts") or "")[:10] or "unknown"
        level = str(ev.get("level") or "INFO").upper()
        msg = str(ev.get("msg") or ev.get("message") or "")[:160]
        txn = str(ev.get("txn") or ev.get("tranid") or "")
        key = f"{src_n}|{ts}"
        by_key.setdefault(key, []).append(f"[{level}] {msg}")
        if txn:
            triples.append({
                "s": f"log:{src_n}:{ts}", "p": "relates_to_txn", "o": txn.upper(),
                "source": rel, "tier": src["tier"], "trust": src["trust"],
                "universe": universe,
            })
        if level in {"WARN", "ERROR"} and msg:
            by_key.setdefault(key, []).append(f"RAW#{i}:{msg}")
    for key, lines in by_key.items():
        src_n, day = key.split("|", 1)
        body = "\n".join(lines[:40])
        if len(body) < 20:
            continue
        chunks.append({
            "chunk_id": hashlib.sha1(f"{rel}:{key}".encode()).hexdigest()[:16],
            "text": f"运维日志摘要 {src_n} @ {day}\n{body}",
            "chunk_index": 0,
            "path": rel,
            "modality": "log",
            "tier": src["tier"],
            "trust": min(0.7, src["trust"]),
            "kind": "ops_log",
            "retrieve_weight": 0.7,
        })
    return chunks, triples


def dedupe_triples(triples: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for t in triples:
        t["s"] = str(t["s"])
        t["o"] = str(t["o"])
        # 已带命名空间时不再二次 normalize 破坏前缀
        if ":" not in t["s"]:
            t["s"] = entity_normalize(t["s"])
        if ":" not in t["o"] and t["p"] not in ("description", "type"):
            t["o"] = entity_normalize(t["o"])
        key = (t["s"], t["p"], t["o"])
        if key not in best or float(t.get("trust", 0)) > float(best[key].get("trust", 0)):
            best[key] = t
    return list(best.values())


def _dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def clean_content_preview(filename: str, content: bytes) -> dict:
    """单文件接入用：内容级隔离/冲突预检（不落盘）。"""
    text = normalize_ws(content.decode("utf-8", errors="replace"))
    path = Path(filename)
    q = should_quarantine(path, text)
    conflicts = detect_content_conflicts(filename, text)
    test_mode = bool(re.search(r"COM-TEST-MODE", text, re.I))
    return {
        "quarantined": q is not None,
        "rule": q[0] if q else None,
        "reason": q[1] if q else None,
        "conflicts": conflicts,
        "test_mode": test_mode,
        "normalized_len": len(text),
    }


def run_dataset_clean(root: Path | None = None, out_dir: Path | None = None) -> CleanResult:
    """扫描数据集并写出清洗产物。"""
    root = (root or default_dataset_root()).resolve()
    if not root.exists():
        raise FileNotFoundError(f"数据集根目录不存在：{root}")
    out_dir = (out_dir or (root / "08_cleaned")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    kg: list[dict] = []
    vec: list[dict] = []
    quar: list[dict] = []
    conflicts: list[dict] = []
    stats: Counter = Counter()
    rule_hits: Counter = Counter()
    input_digest: dict[str, str] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(p in SKIP_DIRS for p in path.parts):
            continue
        suf = path.suffix.lower()
        if suf not in CODE_EXT | DOC_EXT:
            stats["skip_ext"] += 1
            continue
        if path.stat().st_size > 2_000_000:
            stats["skip_huge"] += 1
            rule_hits["R-N2"] += 1
            continue

        rel = str(path.relative_to(root)).replace("\\", "/")
        src = classify_source(rel)
        try:
            raw = path.read_bytes()
            text = normalize_ws(raw.decode("utf-8", errors="replace"))
        except OSError:
            stats["read_fail"] += 1
            continue
        if len(text.strip()) < 20:
            stats["skip_empty"] += 1
            rule_hits["R-N2"] += 1
            continue

        input_digest[rel] = "sha256:" + hashlib.sha256(raw).hexdigest()[:16]
        q = should_quarantine(path, text)
        if q:
            rule, reason = q
            rule_hits[rule] += 1
            quar.append({
                "path": rel, "rule": rule, "reason": reason,
                "tier": src["tier"], "preview": text[:240],
                "role": "adversarial" if rule in {"R-Q2", "R-Q3"} else "quarantine",
            })
            stats["quarantine"] += 1
            continue

        # 版本族旁路：.OLD/.BAK 已在隔离；此处对名中含 V2 且同族并存的降权
        base_stem = VERSION_SUFFIX_RE.sub("", path.stem)
        is_side = bool(VERSION_SUFFIX_RE.search(path.stem))
        trust = src["trust"] * (0.5 if is_side else 1.0)
        if is_side:
            rule_hits["R-D1"] += 1
            conflicts.append({
                "conflict_id": f"cf_ver_{hashlib.sha1(rel.encode()).hexdigest()[:8]}",
                "rule": "R-D1",
                "subject": f"版本族 {base_stem}",
                "sides": [{"claim": "旁路版本", "path": rel, "excerpt": text[:120]}],
                "suggestion": "latest_wins：主版本入正库，本文件降权",
                "status": "pending",
            })

        src_eff = {**src, "trust": trust}

        # 冲突内容检测（不隔离正文，记台账）
        cfs = detect_content_conflicts(rel, text)
        for c in cfs:
            rule_hits[c["rule"]] += 1
        conflicts.extend(cfs)
        test_mode = any(c["rule"] == "R-C6" for c in cfs)

        # 模态分支
        name_l = path.name.lower()
        if suf == ".jsonl" and any(h in name_l for h in LOG_NAME_HINTS):
            log_chunks, log_trips = extract_log_chunks(rel, text, src_eff)
            vec.extend(log_chunks)
            kg.extend(log_trips)
        elif suf == ".mmd":
            kg.extend(extract_mermaid_triples(rel, text, src_eff))
            for ch in chunk_doc(text, rel):
                vec.append({
                    **ch, "path": rel, "modality": "doc", "ext": suf,
                    "tier": src_eff["tier"], "trust": src_eff["trust"],
                    "kind": "mermaid_flow", "retrieve_weight": 0.7,
                    "universe": infer_universe(rel),
                })
        elif suf == ".json" and ("coupling" in name_l or "pair_depend" in name_l
                                 or "call_matrix" in name_l or "modules" in text[:200]):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {}
            kg.extend(extract_coupling_triples(rel, data, src_eff))
            for ch in chunk_doc(text[:4000], rel):
                vec.append({
                    **ch, "path": rel, "modality": "doc", "ext": suf,
                    "tier": src_eff["tier"], "trust": src_eff["trust"],
                    "kind": src_eff["kind"], "retrieve_weight": src_eff["trust"],
                    "universe": infer_universe(rel),
                })
        else:
            kg.extend(extract_triples(rel, text, src_eff))
            if suf in CODE_EXT:
                chunks, modality = chunk_code(text, rel), "code"
            else:
                chunks, modality = chunk_doc(text, rel), "doc"
            for ch in chunks:
                meta = {
                    **ch, "path": rel, "modality": modality, "ext": suf,
                    "tier": src_eff["tier"], "trust": src_eff["trust"],
                    "kind": src_eff["kind"], "lang": "mixed",
                    "retrieve_weight": src_eff["trust"] * (0.7 if test_mode else 1.0),
                    "universe": infer_universe(rel),
                }
                if test_mode:
                    meta["test_mode"] = True
                vec.append(meta)

        stats["files_ok"] += 1
        stats[f"tier_{src['tier']}"] += 1

    kg = dedupe_triples(kg)

    paths = {
        "kg_triples": str(out_dir / "kg_triples.jsonl"),
        "vector_chunks": str(out_dir / "vector_chunks.jsonl"),
        "quarantine": str(out_dir / "quarantine.jsonl"),
        "conflict_ledger": str(out_dir / "conflict_ledger.jsonl"),
        "manifest": str(out_dir / "manifest.json"),
    }
    _dump_jsonl(Path(paths["kg_triples"]), kg)
    _dump_jsonl(Path(paths["vector_chunks"]), vec)
    _dump_jsonl(Path(paths["quarantine"]), quar)
    _dump_jsonl(Path(paths["conflict_ledger"]), conflicts)

    notes = [
        "FR-001(CPS) 与 FR-01(CARD) 不合并，分属不同 universe 命名空间",
        "quarantine 默认不进向量正库；可人工审核后降权入库（role=adversarial）",
        "tier A=github_cobol, B=derived/meta, C=synthetic CPS",
        "实体 ID 形如 CPS:PYMAIN / CARD:FR-01 / VAULT:WIREXFR0",
    ]
    result = CleanResult(
        root=str(root),
        out_dir=str(out_dir),
        generated_at=datetime.now(timezone.utc).isoformat(),
        stats=dict(stats),
        rule_hits=dict(rule_hits),
        kg_triples=len(kg),
        vector_chunks=len(vec),
        quarantine=len(quar),
        conflicts=len(conflicts),
        notes=notes,
        paths=paths,
    )
    manifest = {
        **result.to_dict(),
        "input_digest": input_digest,
    }
    Path(paths["manifest"]).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_manifest(out_dir: Path | None = None) -> dict:
    root = default_dataset_root()
    out_dir = out_dir or (root / "08_cleaned")
    mf = out_dir / "manifest.json"
    if not mf.exists():
        return {}
    return json.loads(mf.read_text(encoding="utf-8"))


def load_jsonl(path: Path, limit: int = 50) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


# 谓词 → 图谱关系
PRED_TO_REL = {
    "calls": "CALLS",
    "uses_dataset": "READS",
    "implemented_by": "IMPLEMENTED_BY",
    "has_tranid": "USES",
    "next_step": "NEXT_STEP",
    "step_of": "STEP_OF",
    "depends_on": "DEPENDS_ON",
    "relates_to_txn": "RELATES_TO",
}


def import_cleaned_to_stores(
    out_dir: Path | None = None,
    *,
    min_trust: float = 0.0,
    include_tier_c: bool = False,
) -> dict:
    """将清洗产物导入图谱与向量库（跳过 quarantine；默认可过滤 C 层）。"""
    from ..llm import get_embedder
    from ..stores.graph import graph_store
    from ..stores.vector import vector_store

    root = default_dataset_root()
    out_dir = out_dir or (root / "08_cleaned")
    kg_path = out_dir / "kg_triples.jsonl"
    vec_path = out_dir / "vector_chunks.jsonl"
    if not kg_path.exists() or not vec_path.exists():
        raise FileNotFoundError("清洗产物不存在，请先执行数据集清洗")

    nodes, edges = 0, 0
    with kg_path.open(encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if float(t.get("trust", 0)) < min_trust:
                continue
            if not include_tier_c and t.get("tier") == "C":
                continue
            if t.get("pending_review"):
                continue  # implemented_by 等需治理通过后再落边
            s, p, o = t["s"], t["p"], t["o"]
            univ = t.get("universe") or "CPS"
            props = {
                "name": s.split(":")[-1], "universe": univ,
                "tier": t.get("tier"), "trust": t.get("trust"),
                "source_path": t.get("source"),
            }
            if p == "type":
                label = {"Program": "CodeUnit", "Requirement": "Requirement",
                         "SubSystem": "TechComponent"}.get(o, o)
                if label == "CodeUnit":
                    props["kind"] = "program"
                graph_store.upsert_node(f"cu/{s}" if label == "CodeUnit" else f"ent/{s}",
                                       label, props)
                nodes += 1
                continue
            rel = PRED_TO_REL.get(p)
            if not rel:
                continue
            src_id = f"cu/{s}" if p in {"calls", "uses_dataset", "has_tranid"} else f"ent/{s}"
            dst_id = f"cu/{o}" if p in {"calls", "implemented_by"} else f"ent/{o}"
            graph_store.upsert_node(src_id, "CodeUnit" if src_id.startswith("cu/") else "Entity",
                                   {"name": s.split(":")[-1], "universe": univ})
            graph_store.upsert_node(dst_id, "CodeUnit" if dst_id.startswith("cu/") else "Entity",
                                   {"name": str(o).split(":")[-1], "universe": univ})
            ep = {"tier": t.get("tier"), "trust": t.get("trust"), "source_path": t.get("source")}
            if "weight" in t:
                ep["weight"] = t["weight"]
            graph_store.upsert_edge(src_id, rel, dst_id, ep)
            edges += 1
    graph_store.save()

    emb = get_embedder()
    n_chunk = 0
    with vec_path.open(encoding="utf-8") as f:
        for line in f:
            ch = json.loads(line)
            if float(ch.get("trust", 0)) < min_trust:
                continue
            if not include_tier_c and ch.get("tier") == "C":
                continue
            modality = ch.get("modality", "doc")
            collection = "kb_code_chunk" if modality == "code" else "kb_doc_chunk"
            text = ch.get("text", "")
            if not text:
                continue
            vec = emb.embed([text])[0]
            meta = {
                "text": text,
                "source_path": ch.get("path"),
                "title": ch.get("path", ""),
                "doc_type": modality,
                "tier": ch.get("tier"),
                "trust": ch.get("trust"),
                "kind": ch.get("kind"),
                "universe": ch.get("universe"),
                "retrieve_weight": ch.get("retrieve_weight", ch.get("trust")),
                "loc": f"chunk:{ch.get('chunk_index', 0)}",
            }
            if modality == "code":
                meta["code_unit"] = Path(ch.get("path", "")).stem
                meta["lang"] = "COBOL"
            vector_store.upsert(collection, f"clean/{ch['chunk_id']}", vec, meta)
            n_chunk += 1
    vector_store.save()
    return {"nodes": nodes, "edges": edges, "chunks": n_chunk,
            "out_dir": str(out_dir)}
