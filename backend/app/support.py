"""迁移支撑：影响分析（设计 7.7）与代码骨架生成（含免责声明）。"""
from __future__ import annotations

from .stores.graph import graph_store

DISCLAIMER = "生成代码仅作开发骨架参考，不直接在主机环境运行测试"


def analyze_impact(target: str, change_summary: str = "", depth: int = 3) -> dict:
    nodes = graph_store.find_by_name(target)
    if not nodes:
        return {"found": False, "message": f"未在图谱中找到对象：{target}"}
    node = nodes[0]
    sub = graph_store.impact(node["id"], depth=depth)
    affected_interfaces = sub["by_label"].get("Interface", 0)
    affected_subsystems = sub["by_label"].get("SubSystem", 0) + sub["by_label"].get("System", 0)
    coupling = sub["coupling_score"]
    risk = "high" if coupling >= 0.6 else ("medium" if coupling >= 0.3 else "low")
    return {
        "found": True,
        "target": target,
        "change_summary": change_summary,
        "affected": {
            "total": sub["affected"],
            "interfaces": affected_interfaces,
            "subsystems": affected_subsystems,
            "code_units": sub["by_label"].get("CodeUnit", 0),
            "data_tables": sub["by_label"].get("DataTable", 0) + sub["by_label"].get("Field", 0),
            "by_label": sub["by_label"],
        },
        "metrics": {"coupling_score": coupling, "history_defect_rate": None},
        "risk_level": risk,
        "evidence": sub["paths"][:12],
        "depth": depth,
    }


def generate_skeleton(interface_name: str, target: str = "spring_controller") -> dict:
    nodes = graph_store.find_by_name(interface_name)
    node = nodes[0] if nodes else None
    fields: list[dict] = []
    if node:
        _, edges = graph_store.neighbors(node["id"], max_hops=2, rels={"USES", "HAS_FIELD"})
        field_ids = {e["dst"] for e in edges if e["rel"] == "HAS_FIELD"}
        for fid in field_ids:
            f = graph_store.node(fid)
            if f:
                fields.append({"name": f["props"].get("name", "").split(".")[-1],
                               "type": f["props"].get("type", "String"),
                               "desc": f["props"].get("desc", "")})
    review_points = ["货币转换精度", "幂等控制", "异常码映射与错误码表对齐", "字段映射规则人工确认"]
    if target == "python_script":
        body = _python_skeleton(interface_name, fields)
        lang = "python"
    else:
        body = _java_skeleton(interface_name, fields)
        lang = "java"
    return {
        "found": node is not None,
        "files": [{"path": _file_name(interface_name, target),
                   "language": lang, "content": body, "review_points": review_points}],
        "disclaimer": DISCLAIMER,
    }


def _java_skeleton(interface_name: str, fields: list[dict]) -> str:
    cls = "".join(w.capitalize() for w in interface_name.split("_")) or "Skeleton"
    dto_fields = "\n".join(
        f"    /** {f['desc'] or f['name']} */\n    private String {f['name'].lower()};"
        for f in fields) or "    private String placeholder;"
    return f"""// {interface_name} —— 由知识库生成的接口骨架（依据图谱与 mapping）
// 注意：{DISCLAIMER}
package com.bank.migration.skeleton;

public class {cls}Controller {{

    // 请求/响应字段（来源：知识图谱报文定义）
{dto_fields}

    // POST /{interface_name}
    public {cls}Response handle({cls}Request req) {{
        // TODO[人工校验]: 按错误码表映射返回码
        // TODO[人工校验]: 货币转换精度处理
        // TODO[人工校验]: 幂等控制
        validate(req);
        return doBusiness(req);
    }}

    private void validate(Object req) {{ /* 依据业务规则节点补全校验 */ }}

    private {cls}Response doBusiness(Object req) {{ throw new UnsupportedOperationException(); }}
}}
"""


def _python_skeleton(interface_name: str, fields: list[dict]) -> str:
    cols = "\n".join(f"    {f['name'].lower()}: str  # {f['desc'] or ''}" for f in fields) or "    placeholder: str"
    return f"""# {interface_name} —— 由知识库生成的处理脚本骨架
# 注意：{DISCLAIMER}
from dataclasses import dataclass


@dataclass
class Record:
{cols}


def process(record: Record) -> dict:
    # TODO[人工校验]: 按错误码表映射返回码
    # TODO[人工校验]: 字段映射转换规则
    validate(record)
    return {{"code": 0, "message": "success"}}


def validate(record: Record) -> None:
    ...
"""


def _file_name(interface_name: str, target: str) -> str:
    if target == "python_script":
        return f"{interface_name}_job.py"
    cls = "".join(w.capitalize() for w in interface_name.split("_")) or "Skeleton"
    return f"{cls}Controller.java"
