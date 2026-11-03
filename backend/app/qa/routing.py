"""Select a bounded QA flow without spending an LLM round on tool selection."""
import re

from ..config import settings
from ..knowledge.query_parser import parse_query
from .analyzer import classify_intent


def choose_orchestrator(question, history=None, requested='auto'):
    if requested in {'flow', 'agent'}:
        return requested
    if settings.kb_qa_strategy != 'auto':
        return settings.kb_qa_strategy
    plan = parse_query(question, history)
    narrative = plan.narrative.lower()
    if plan.mode == 'similar' or classify_intent(narrative) == 'impact_analysis':
        return 'agent'
    # Inspect the user's request, not identifiers or comments inside pasted code.
    if re.search(r'调用链|跨(?:文件|程序|模块|文档)|多跳|完整流程|逐步排查|对比|比较|'
                 r'(?:完整|所有|全部|全量).{0,12}(?:字段|依赖|调用|流程)|'
                 r'call\s+chain|multi[- ]hop|compare', narrative):
        return 'agent'
    return 'flow'
