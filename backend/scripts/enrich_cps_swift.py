"""拉取 Prowide MT103 示例，写入 hf_data 并灌入向量库。"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "hf_data" / "07_derived" / "01_tech_docs" / "swift"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    api = (
        "https://api.github.com/repos/prowide/prowide-core-examples/"
        "contents/src/main/java/com/prowidesoftware/swift/samples/core?ref=main"
    )
    files = json.load(urllib.request.urlopen(api, timeout=30))
    pick = None
    for f in files:
        if f.get("type") != "file":
            continue
        name = f["name"].lower()
        if "mt103" in name and f.get("download_url"):
            pick = f
            break
    if pick is None:
        for f in files:
            if f.get("type") == "file" and "parse" in f["name"].lower() and f.get("download_url"):
                pick = f
                break
    code = ""
    html = "https://github.com/prowide/prowide-core-examples"
    fname = "(none)"
    if pick:
        code = urllib.request.urlopen(pick["download_url"], timeout=30).read().decode(
            "utf-8", "replace"
        )
        (OUT / pick["name"]).write_text(code, encoding="utf-8")
        html = pick.get("html_url") or html
        fname = pick["name"]

    note = f"""# CPS 跨境汇出与 SWIFT MT103 参考

> 外部参考（GitHub）：{html}
> 本地权威：`01_tech_docs/architecture/ARCH-PAY-001_跨境支付核心架构设计书.md`
> 本地需求：`03_business_rules/requirements/SRS-CPS-SWIFT-001_需求规格说明书.md`

## CPS 一笔跨境汇出关键路径（同步交易）

1. CGW 接收客户指令 → MQ `CPS.IN.Q`
2. CICS 交易 PYIN 触发 PYMAIN
3. PYVAL 校验 → AML 异步筛查（MQ `AML.SCR.Q`）
4. PYROUTE 选路 → PYPOST 记账
5. PYMSGOT 出站（SWIFT MT103 / pacs.008 等）→ 更新 `PY_TXN_STATUS`

## 与 SWIFT MT103 的关系

- FR-001：解析 MT103 字段 20/32A/50/59/70
- 报文接入 MSGIN / 出站 MSGOT（PYMSGOT）
- 下列开源示例展示 MT103 解析 API（Prowide Core）

## GitHub 示例：{fname}

```java
{code[:4000] if code else '// fetch failed'}
```
"""
    bridge = OUT / "CPS_SWIFT_CRITICAL_PATH.md"
    bridge.write_text(note, encoding="utf-8")

    from app.llm import get_embedder
    from app.stores.vector import vector_store

    emb = get_embedder().embed([note])[0]
    vector_store.upsert(
        "kb_doc_chunk",
        "cps/swift_critical_path_bridge",
        emb,
        {
            "text": note,
            "source_path": "07_derived/01_tech_docs/swift/CPS_SWIFT_CRITICAL_PATH.md",
            "title": "CPS跨境汇出关键路径与SWIFT参考",
            "doc_type": "doc",
            "tier": "B",
            "trust": 0.92,
            "kind": "architecture",
            "universe": "CPS",
            "retrieve_weight": 1.0,
            "loc": "full",
        },
    )
    vector_store.save()
    print("wrote", bridge, "bytes", bridge.stat().st_size, "example", fname)


if __name__ == "__main__":
    main()
