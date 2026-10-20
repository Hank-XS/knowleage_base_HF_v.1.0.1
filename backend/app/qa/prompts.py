"""Skills 回答骨架（设计 8.4 节），场景配置化。"""

SKILLS_SKELETON = """[role] 你是核心系统迁移知识库的问答助手，服务研发、业务与架构人员。
[scene] 当前场景：{scene_code}；场景知识仅来自本次检索证据，不得凭参数记忆编造。
[answer_structure]
  1. what（是什么）：先给结论，一句话说明对象与状态；
  2. why（为什么）：基于证据给出成因链路，逐条标注来源编号；
  3. how（怎么处理）：给出可执行步骤；涉及业务规则的，标注需人工复核。
[citation] 每条事实性陈述必须挂接来源编号；知识库未覆盖时显式声明 uncovered=true，禁止编造。
[output] 严格输出 JSON：{{"what": str, "why": str, "how": str, "caveats": [str], "confidence": 0~1, "uncovered": bool}}
[boundary] 不承诺业务正确性（以人工复核为准）；不生成用于直接上机运行的代码。"""

MOCK_QA_KEY = "__mock_qa__"


def build_synthesis_messages(scene_code: str, question: str, evidence_lines: list[str],
                             reference: str = "", history_lines: list[str] | None = None,
                             mock: bool = False, evidence: list[dict] | None = None) -> list[dict]:
    """组装合成提示。mock=True 时构造 MockLLM 可识别的证据负载。"""
    ev_text = "\n".join(f"[{i}] {ln}" for i, ln in enumerate(evidence_lines, start=1))
    sys = SKILLS_SKELETON.format(scene_code=scene_code)
    parts = [f"问题：{question}"]
    if reference:
        parts.append(f"参考上下文（相似历史答案，压缩版，仅供参照不得直接照抄）：\n{reference}")
    if history_lines:
        parts.append("会话历史（摘要）：\n" + "\n".join(history_lines[-4:]))
    parts.append(f"检索证据：\n{ev_text or '（无）'}")
    user = json_mock_payload(question, evidence or []) if mock else "\n\n".join(parts)
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def json_mock_payload(question: str, evidence: list[dict]) -> str:
    import json
    ev = [{"label": e.get("label") or e.get("ref", ""), "ref": e.get("ref", ""),
           "text": e.get("text", "")} for e in evidence]
    return json.dumps({MOCK_QA_KEY: True, "question": question, "evidence": ev}, ensure_ascii=False)
