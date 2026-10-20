#!/usr/bin/env python3
"""
hf_data → 知识图谱边 / 向量库 chunk 的清洗脚本（测试数据用）

产出:
  08_cleaned/kg_triples.jsonl     实体三元组
  08_cleaned/vector_chunks.jsonl  带元数据的文本块
  08_cleaned/quarantine.jsonl     被隔离（密钥/屎山旁路/死代码等）
  08_cleaned/manifest.json        统计与来源

用法:
  python clean_corpus.py
  python clean_corpus.py --root C:\\Users\\139568\\hf_data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ---------- 策略开关 ----------
SKIP_DIRS = {
    ".git",
    "08_cleaned",  # 不递归自己
}
# 故意屎山 / 假密钥 / 未完成 V2：默认进隔离区，不当正训
QUARANTINE_NAME_HINTS = (
    "FIX_TMP_",
    "PYMAIN.OLD",
    "PYRECON#.BAK",
    "_LANDMINES",
    "DLQ_REPLAY_V2",
    "COMMON.cpy",
    "cps_smoke_deploy.sh",  # 内含硬编码假密钥
)
QUARANTINE_CONTENT_RES = [
    re.compile(r"P@ssw0rd|client_secret\s*=\s*\S+", re.I),
    re.compile(r"VIP.?skip.?aml|skip aml|TESTSKIPAML", re.I),
    re.compile(r"7777-DEAD-CODE|DO NOT USE|dont submit", re.I),
    re.compile(r"exit 0\s*#.*jenkins green|失败.*exit 0", re.I),
]
# 来源分层：图谱/向量应用不同权重
SOURCE_TIER = {
    "02_code_assets/github_cobol": {"tier": "A", "trust": 0.95, "kind": "upstream_code"},
    "07_derived": {"tier": "B", "trust": 0.75, "kind": "derived_from_code"},
    "01_tech_docs": {"tier": "C", "trust": 0.55, "kind": "synthetic_doc"},
    "02_code_assets": {"tier": "C", "trust": 0.50, "kind": "synthetic_code"},
    "03_business_rules": {"tier": "C", "trust": 0.55, "kind": "synthetic_doc"},
    "04_system_metadata": {"tier": "B", "trust": 0.70, "kind": "synthetic_meta"},
}

CODE_EXT = {".cbl", ".cob", ".cpy", ".jcl", ".rpgle", ".rex", ".sql", ".mqsc"}
DOC_EXT = {".md", ".yaml", ".yml", ".json", ".jsonl", ".csv", ".mmd", ".txt"}

PROG_ID_RE = re.compile(
    r"PROGRAM-ID\.\s*([A-Z0-9][A-Z0-9-]*)", re.I
)
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


def classify_source(rel: str) -> dict:
    rel_n = rel.replace("\\", "/")
    for prefix, meta in sorted(SOURCE_TIER.items(), key=lambda x: -len(x[0])):
        if rel_n.startswith(prefix):
            return {**meta, "prefix": prefix}
    return {"tier": "D", "trust": 0.3, "kind": "other", "prefix": ""}


def should_quarantine(path: Path, text: str) -> str | None:
    name = path.name
    for h in QUARANTINE_NAME_HINTS:
        if h.lower() in name.lower() or h.lower() in str(path).lower():
            return f"name_hint:{h}"
    for rx in QUARANTINE_CONTENT_RES:
        if rx.search(text):
            return f"content:{rx.pattern[:40]}"
    return None


def normalize_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # COBOL 固定列注释：把整行以 * 在第7列附近的常见情况保留，去掉 NUL
    text = text.replace("\x00", "")
    return text


def strip_cobol_noise(text: str) -> str:
    """去掉大段版权头、连续空行，保留 PROCEDURE / CALL 信号。"""
    lines = text.split("\n")
    out = []
    skip_license = False
    for ln in lines:
        u = ln.upper()
        if "LICENSED UNDER THE APACHE" in u or "COPYRIGHT AMAZON" in u:
            skip_license = True
        if skip_license:
            if u.strip().startswith("IDENTIFICATION DIVISION") or u.strip().startswith(
                "PROGRAM-ID"
            ):
                skip_license = False
            else:
                continue
        out.append(ln.rstrip())
    # 压连续空行
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


def chunk_code(text: str, path: str, max_chars: int = 3500) -> list[dict]:
    """按段落/SECTION 切，失败则定长切。"""
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
        chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
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
    """按 markdown 标题 / 空行切。"""
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


def extract_triples(path: Path, text: str, src: dict) -> list[dict]:
    rel = str(path)
    triples = []
    pid = PROG_ID_RE.search(text)
    program = pid.group(1).upper() if pid else None
    if program:
        triples.append(
            {
                "s": program,
                "p": "type",
                "o": "Program",
                "source": rel,
                "tier": src["tier"],
                "trust": src["trust"],
            }
        )
    for m in CALL_RE.finditer(text):
        callee = m.group(1).upper()
        if program and callee != program:
            triples.append(
                {
                    "s": program,
                    "p": "calls",
                    "o": callee,
                    "source": rel,
                    "tier": src["tier"],
                    "trust": src["trust"],
                }
            )
    for m in TRAN_RE.finditer(text):
        if program:
            triples.append(
                {
                    "s": program,
                    "p": "has_tranid",
                    "o": m.group(1).upper(),
                    "source": rel,
                    "tier": src["tier"],
                    "trust": src["trust"],
                }
            )
    for m in DATASET_RE.finditer(text):
        ds = m.group(1).upper()
        if program and len(ds) >= 4 and not ds.startswith("PIC"):
            triples.append(
                {
                    "s": program,
                    "p": "uses_dataset",
                    "o": ds,
                    "source": rel,
                    "tier": src["tier"],
                    "trust": max(0.3, src["trust"] - 0.15),
                }
            )
    if path.suffix.lower() in {".md", ".csv"}:
        for m in FR_RE.finditer(text):
            fr_id, desc = m.group(1).upper(), m.group(2).strip()
            triples.append(
                {
                    "s": fr_id,
                    "p": "type",
                    "o": "Requirement",
                    "source": rel,
                    "tier": src["tier"],
                    "trust": src["trust"],
                }
            )
            triples.append(
                {
                    "s": fr_id,
                    "p": "description",
                    "o": desc[:200],
                    "source": rel,
                    "tier": src["tier"],
                    "trust": src["trust"],
                }
            )
            # 描述里出现的程序名粗链
            for tok in re.findall(r"`([A-Z][A-Z0-9]{3,})`", desc, re.I):
                triples.append(
                    {
                        "s": fr_id,
                        "p": "implemented_by",
                        "o": tok.upper(),
                        "source": rel,
                        "tier": src["tier"],
                        "trust": src["trust"] * 0.9,
                    }
                )
    return triples


def entity_normalize(name: str) -> str:
    """简单实体归一：去掉路径噪声、统一大小写。"""
    n = name.strip().upper()
    n = n.replace(".CBL", "").replace(".COB", "")
    aliases = {
        "PYMAIN2": "PYMAIN",
        "CPS.IN": "CPS.IN.Q",
        "FR-01": "FR-01",
        "FR-001": "FR-001",  # CPS 与 CARD 编号体系不同，不强行合并
    }
    return aliases.get(n, n)


def dedupe_triples(triples: list[dict]) -> list[dict]:
    best = {}
    for t in triples:
        t["s"] = entity_normalize(str(t["s"]))
        t["o"] = entity_normalize(str(t["o"]))
        key = (t["s"], t["p"], t["o"])
        if key not in best or t["trust"] > best[key]["trust"]:
            best[key] = t
    return list(best.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root: Path = args.root
    out_dir = root / "08_cleaned"
    out_dir.mkdir(exist_ok=True)

    kg, vec, quar = [], [], []
    stats = Counter()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(p in SKIP_DIRS for p in path.parts):
            continue
        if path.suffix.lower() not in CODE_EXT | DOC_EXT:
            stats["skip_ext"] += 1
            continue
        # 跳过过大二进制误入
        if path.stat().st_size > 2_000_000:
            stats["skip_huge"] += 1
            continue

        rel = str(path.relative_to(root)).replace("\\", "/")
        src = classify_source(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stats["read_fail"] += 1
            continue
        text = normalize_ws(text)
        if len(text.strip()) < 20:
            stats["skip_empty"] += 1
            continue

        qreason = should_quarantine(path, text)
        if qreason:
            quar.append(
                {
                    "path": rel,
                    "reason": qreason,
                    "tier": src["tier"],
                    "preview": text[:240],
                }
            )
            stats["quarantine"] += 1
            continue

        # KG
        trips = extract_triples(path, text, src)
        kg.extend(trips)

        # Vector chunks
        if path.suffix.lower() in CODE_EXT:
            chunks = chunk_code(text, rel)
            modality = "code"
        else:
            chunks = chunk_doc(text, rel)
            modality = "doc"

        for ch in chunks:
            vec.append(
                {
                    **ch,
                    "path": rel,
                    "modality": modality,
                    "ext": path.suffix.lower(),
                    "tier": src["tier"],
                    "trust": src["trust"],
                    "kind": src["kind"],
                    "lang": "mixed",
                    # 训练/检索权重提示：A 源码 > B 反推 > C 虚构
                    "retrieve_weight": src["trust"],
                }
            )
        stats["files_ok"] += 1
        stats[f"tier_{src['tier']}"] += 1

    kg = dedupe_triples(kg)

    def dump_jsonl(p: Path, rows: list):
        with p.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump_jsonl(out_dir / "kg_triples.jsonl", kg)
    dump_jsonl(out_dir / "vector_chunks.jsonl", vec)
    dump_jsonl(out_dir / "quarantine.jsonl", quar)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "stats": dict(stats),
        "kg_triples": len(kg),
        "vector_chunks": len(vec),
        "quarantine": len(quar),
        "notes": [
            "FR-001(CPS) 与 FR-01(CARD) 不合并，分属不同 universe",
            "quarantine 默认不进向量正库；可人工审核后降权入库",
            "tier A=github_cobol, B=derived/meta, C=synthetic CPS",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
