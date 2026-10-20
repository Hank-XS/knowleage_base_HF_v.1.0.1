"""ATM 场景种子数据：模拟客户提供素材，走与真实接入完全相同的离线管线。"""
from __future__ import annotations

from pathlib import Path

from .config import SEED_DIR
from .ingest.parsers import parse_by_type
from .ingest.pipeline import create_job, run_job
from .stores.graph import graph_store
from .stores.objects import object_store
from .db import SessionLocal, User
from .deps import hash_password

CARDS_SPEC = {
    "name": "card_caliber", "direction": "meta",
    "calibers": {
        "three-kind": ["借记卡", "贷记卡", "准贷记卡"],
        "six-kind": ["Smart卡", "HBC卡", "借记卡", "贷记卡", "准贷记卡", "预付卡"],
    },
    "aliases": {"Smart卡": "借记卡", "HBC卡": "贷记卡"},
}

FUNCTION_POINTS = [
    {"name": "ATM取款", "desc": "客户在ATM渠道发起取款交易，含余额校验、出钞与记账",
     "interfaces": ["if_atm_withdraw"], "rules": ["余额校验规则", "日限额规则"],
     "processes": ["余额校验", "出钞控制", "记账"]},
    {"name": "ATM余额查询", "desc": "查询账户可用余额与冻结金额",
     "interfaces": ["if_atm_balance"], "rules": ["余额校验规则"], "processes": ["余额查询"]},
]

STRUCTURE = {
    "systems": [("sys/core", "核心账务系统")],
    "subsystems": [("sub/atm", "ATM渠道子系统", "sys/core"),
                   ("sub/deposit", "存款模块", "sys/core")],
    "interfaces": [("if_atm_withdraw", "ATM取款接口", "sub/atm"),
                   ("if_atm_balance", "ATM余额查询接口", "sub/atm")],
    "rules": [("rule/balance_check", "余额校验规则", "校验可用余额≥交易金额，境外卡需币种转换后额度校验"),
              ("rule/daily_limit", "日限额规则", "单卡单日取款累计不超过等值2万元人民币")],
    "implements": [("rule/balance_check", "cu/ATMWD402.4020-CHECK-BAL"),
                   ("rule/daily_limit", "cu/ATMWD402.4030-CHECK-LIMIT")],
    "realized_by": [("fp/ATM取款", "if_atm_withdraw"), ("fp/ATM余额查询", "if_atm_balance")],
}


def seed_structure() -> None:
    for nid, name in STRUCTURE["systems"]:
        graph_store.upsert_node(nid, "System", {"name": name})
    for nid, name, parent in STRUCTURE["subsystems"]:
        graph_store.upsert_node(nid, "SubSystem", {"name": name})
        graph_store.upsert_edge(nid, "PART_OF", parent)
    for nid, name, parent in STRUCTURE["interfaces"]:
        graph_store.upsert_node(nid, "Interface", {"name": name, "protocol": "CICS", "daily_calls": 120000})
        graph_store.upsert_edge(nid, "PART_OF", parent)
    for nid, name, desc in STRUCTURE["rules"]:
        graph_store.upsert_node(nid, "BusinessRule", {"name": name, "desc": desc, "effective_date": "2019-01-01"})
    for src, dst in STRUCTURE["implements"]:
        graph_store.upsert_edge(src, "IMPLEMENTED_BY", dst)
    for src, dst in STRUCTURE["realized_by"]:
        graph_store.upsert_edge(src, "REALIZED_BY", dst)
    for fp in FUNCTION_POINTS:
        fpid = graph_store.upsert_node(f"fp/{fp['name']}", "FunctionPoint",
                                       {"name": fp["name"], "desc": fp["desc"]})
        for p in fp["processes"]:
            pid = graph_store.upsert_node(f"bp/{p}", "BusinessProcess", {"name": p})
            graph_store.upsert_edge(fpid, "PART_OF", pid)
    # 卡种多口径
    node_ids = {}
    for caliber, names in CARDS_SPEC["calibers"].items():
        for nm in names:
            cid = f"card/{nm}"
            graph_store.upsert_node(cid, "CardType", {"name": nm, "caliber": caliber})
            node_ids[nm] = cid
    for alias, main in CARDS_SPEC["aliases"].items():
        graph_store.upsert_edge(node_ids[alias], "ALIAS_OF", node_ids[main],
                                {"note": "六种口径别名归一到三种口径"})


def seed_users() -> None:
    demo_users = [
        ("admin", "admin123", "admin", "系统管理员"),
        ("dev01", "dev123456", "dev", "研发人员"),
        ("biz01", "biz123456", "biz", "业务人员"),
        ("gov01", "gov123456", "gov", "治理员"),
    ]
    with SessionLocal() as db:
        for u, p, r, n in demo_users:
            row = db.query(User).filter(User.username == u).one_or_none()
            pwd = hash_password(p)
            if row is None:
                db.add(User(username=u, pwd_hash=pwd, role=r, display_name=n))
            else:
                # JWT_SECRET 变更后同步刷新演示账号口令哈希
                row.pwd_hash = pwd
                row.role = r
                row.display_name = n
        db.commit()


def seed_knowledge(force: bool = False) -> dict:
    """把 data/seed 下素材经对象存储 → 离线管线 → 图谱/向量 全链路入库。"""
    if not force and graph_store.stats()["nodes"] > 0:
        return {"skipped": True, "reason": "知识库已有数据"}
    seed_structure()
    counts = {}
    for f in sorted(SEED_DIR.rglob("*")):
        if f.suffix.lower() not in (".csv", ".json", ".md", ".txt", ".cbl"):
            continue
        source_type = None
        rel = f.relative_to(SEED_DIR).as_posix()
        if "error_codes" in rel:
            source_type = "error_code_table"
        elif "mapping" in rel:
            source_type = "mapping"
        elif "messages" in rel:
            source_type = "message_format"
        elif "cobol" in rel:
            source_type = "cobol"
        else:
            source_type = "doc"
        if source_type is None:
            continue
        key = object_store.inbox(source_type, f.name)
        object_store.put(key, f.read_bytes())
        job_id = create_job(source_type, [key])
        run_job(job_id)
        counts[rel] = source_type
    graph_store.save()
    return {"skipped": False, "files": counts}
