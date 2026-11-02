"""Public answer text and optional supporting detail share one JSON contract."""
import json


ANSWER_GUIDANCE = """[writing]
summary 是直接给用户看的答案，先回答所问，再给必要的行动建议；使用纯文本，可分行列点，不输出 Markdown 标题。
普通问题控制在约 150~250 个中文字，最多 3 个要点；简单问题一句话即可。
用户明确要求详细解释、完整清单或代码时按要求展开，不机械限制长度。
使用清楚的业务语言，保留关键程序名、字段名与必要的不确定性；不描述检索步骤或工具执行过程。
what/why/how 存放补充说明，避免重复 summary。没有证据支持时直说无法确认，不把相关片段当成已证实结论。
证据编号只放在补充说明中，summary 不堆砌来源编号。"""


def parse_answer(raw: str) -> dict:
    try:
        start, end = raw.find('{'), raw.rfind('}')
        data = json.loads(raw[start:end + 1])
        if not isinstance(data, dict):
            raise ValueError('Expected answer object')
    except (ValueError, TypeError, AttributeError):
        data = dict(what=(raw or '').strip()[:500], confidence=0.4, uncovered=False)
    result = {key: data.get(key, '' if key != 'caveats' else []) for key in
              ('summary', 'what', 'why', 'how', 'caveats', 'confidence', 'uncovered')}
    # Old/cached answers remain complete; no character slicing of valid model answers.
    if not result['summary']:
        result['summary'] = result['what'] or result['how'] or result['why']
    return result
