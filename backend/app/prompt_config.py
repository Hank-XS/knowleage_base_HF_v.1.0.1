"""式样书提示词配置：按类型维护 system prompt（供 /codegen/spec 读取）。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select

from .db import PromptTemplate, SessionLocal
from .response import KbError


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

PROMPT_TYPES = ("program", "interface", "batch", "copybook")

TYPE_TITLES = {
    "program": "程序式样书",
    "interface": "接口式样书",
    "batch": "批处理式样书",
    "copybook": "数据结构/COPYBOOK 式样书",
}

_COMMON_TAIL = """
[输出要求]
1. 严格按下列章节输出 Markdown，缺信息处写「待确认」并标注需人工复核；
2. 事实性描述须可追溯到输入材料（代码/需求/证据），禁止编造业务规则；
3. 不生成可直接上机运行的完整代码，仅描述规格与要点。

[章节骨架]
## 1. 概述
## 2. 输入输出
## 3. 处理逻辑
## 4. 异常与返回码
## 5. 依据与备注
"""

DEFAULT_PROMPTS: dict[str, str] = {
    "program": f"""[role] 你是主机核心系统迁移的程序式样书撰写助手。
[scope] 根据给定程序（COBOL/CICS 等）的源码与知识库证据，整理程序设计式样书。
[focus] 程序标识、段结构、CALL/COPY、关键数据区、与外围（MQ/DB2/VSAM/CICS）交互。
{_COMMON_TAIL}""",
    "interface": f"""[role] 你是主机核心系统迁移的接口式样书撰写助手。
[scope] 根据接口定义、报文样例与知识库证据，整理接口式样书。
[focus] 接口标识、协议（MQ/REST/CICS LINK）、请求/响应字段、校验规则、超时与重试。
{_COMMON_TAIL}""",
    "batch": f"""[role] 你是主机核心系统迁移的批处理式样书撰写助手。
[scope] 根据 JCL/作业步骤、依赖与知识库证据，整理批处理式样书。
[focus] 作业名、步骤、输入输出数据集、依赖编排、重跑与对账要点。
{_COMMON_TAIL}""",
    "copybook": f"""[role] 你是主机核心系统迁移的数据结构式样书撰写助手。
[scope] 根据 COPYBOOK/数据字典与知识库证据，整理数据结构式样书。
[focus] 记录布局、字段含义、长度/类型、重定义、使用该结构的程序清单。
{_COMMON_TAIL}""",
}


def _row_dict(row: PromptTemplate) -> dict[str, Any]:
    return {
        "type": row.type,
        "title": row.title,
        "system_prompt": row.system_prompt,
        "enabled": bool(row.enabled),
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def ensure_prompt_defaults() -> int:
    """缺失类型补齐默认提示词；返回新建条数。"""
    created = 0
    with SessionLocal() as db:
        for t in PROMPT_TYPES:
            row = db.get(PromptTemplate, t)
            if row is not None:
                continue
            db.add(PromptTemplate(
                type=t,
                title=TYPE_TITLES[t],
                system_prompt=DEFAULT_PROMPTS[t].strip(),
                enabled=1,
                updated_by="system",
            ))
            created += 1
        if created:
            db.commit()
    return created


def list_prompts() -> list[dict[str, Any]]:
    ensure_prompt_defaults()
    with SessionLocal() as db:
        rows = db.execute(
            select(PromptTemplate).order_by(PromptTemplate.type)
        ).scalars().all()
    # 按预置顺序排列
    by_type = {r.type: r for r in rows}
    return [_row_dict(by_type[t]) for t in PROMPT_TYPES if t in by_type]


def get_prompt(prompt_type: str) -> dict[str, Any]:
    ensure_prompt_defaults()
    if prompt_type not in PROMPT_TYPES:
        raise KbError("40001", f"未知类型: {prompt_type}")
    with SessionLocal() as db:
        row = db.get(PromptTemplate, prompt_type)
        if row is None:
            raise KbError("40401", "提示词不存在")
        return _row_dict(row)


def update_prompt(prompt_type: str, *, title: str | None = None,
                  system_prompt: str | None = None, enabled: bool | None = None,
                  actor: str = "") -> dict[str, Any]:
    ensure_prompt_defaults()
    if prompt_type not in PROMPT_TYPES:
        raise KbError("40001", f"未知类型: {prompt_type}")
    with SessionLocal() as db:
        row = db.get(PromptTemplate, prompt_type)
        if row is None:
            raise KbError("40401", "提示词不存在")
        if title is not None:
            row.title = title.strip() or TYPE_TITLES[prompt_type]
        if system_prompt is not None:
            if not system_prompt.strip():
                raise KbError("40001", "system_prompt 不能为空")
            row.system_prompt = system_prompt
        if enabled is not None:
            row.enabled = 1 if enabled else 0
        row.updated_by = actor or row.updated_by
        row.updated_at = _now()
        db.commit()
        db.refresh(row)
        return _row_dict(row)


def reset_prompt(prompt_type: str, actor: str = "") -> dict[str, Any]:
    ensure_prompt_defaults()
    if prompt_type not in PROMPT_TYPES:
        raise KbError("40001", f"未知类型: {prompt_type}")
    with SessionLocal() as db:
        row = db.get(PromptTemplate, prompt_type)
        if row is None:
            row = PromptTemplate(type=prompt_type)
            db.add(row)
        row.title = TYPE_TITLES[prompt_type]
        row.system_prompt = DEFAULT_PROMPTS[prompt_type].strip()
        row.enabled = 1
        row.updated_by = actor or "system"
        row.updated_at = _now()
        db.commit()
        db.refresh(row)
        return _row_dict(row)
