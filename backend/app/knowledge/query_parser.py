"""Server-owned routing for the single chat input; code is data, never instructions."""
from dataclasses import dataclass
import re


FENCE = re.compile(r'(?m)^\s*(`{3,}|~{3,})([\w+-]*)[^\n]*\n(.*?)(?:^\s*\1\s*$|\Z)', re.S | re.M)
CODE_LINE = re.compile(r'^\s*(?:\d{6})?\s*(?:'
    r'(?:IDENTIFICATION|PROCEDURE|DATA|ENVIRONMENT)\s+DIVISION\b|PROGRAM-ID\.|'
    r'(?:MOVE\s+.+\s+TO|CALL\s+[\w\"\']|PERFORM\s+[\w-]+|COMPUTE\s+|'
    r'IF\s+[\w-]+\s*(?:[<>=]|IS\b)|END-IF\b|\d{2}\s+[\w-]+\s+PIC\b)|'
    r'(?:def|class|function)\s+\w+|(?:SELECT\s+.+\s+FROM|UPDATE\s+\w+\s+SET)\b)', re.I)


@dataclass(frozen=True)
class QueryPlan:
    mode: str
    narrative: str
    code: str = ''
    language: str = ''
    inherited: bool = False

    @property
    def scope_query(self):
        # A CALL target or variable in a pasted snippet is not its owning file.
        if self.mode == 'similar':
            return re.sub(r'\b[\w-]+\.(?:cbl|cob|cpy)\b', '', self.narrative, flags=re.I)
        subject = re.search(r'\bPROGRAM-ID\.\s*([\w-]+)', self.code, re.I)
        return self.narrative + (' ' + subject[1] if subject and self.mode == 'source' else '')

    @property
    def guidance(self):
        return {
            'source': '本次任务为代码来源定位。仅当原文匹配证实后才称为同一代码，提供文件与行号；相似片段必须明确说明不是已确认的原始实现。',
            'similar': '本次任务为相似逻辑检索。比较条件、常量、异常分支与调用差异，相关或结构相似不代表行为等价。',
            'business': '本次任务为知识问答。优先回答业务问题，结合相关文档与代码原文；不从名称或缺失实现推导业务事实。',
        }[self.mode]


def parse_query(text, history=None):
    text = text.strip()
    matches = list(FENCE.finditer(text))
    blocks, languages = [], []
    narrative = text
    for match in matches:
        # Fixed-format COBOL comment columns and leading whitespace inside literals matter.
        lang, body = match[2].lower(), match[3].strip('\r\n')
        if lang in {'cobol', 'cbl', 'sql', 'python', 'py', 'java', 'javascript', 'js', 'typescript', 'ts'} or any(CODE_LINE.search(line) for line in body.splitlines()):
            blocks.append(body); languages.append(lang)
            narrative = narrative.replace(match[0], '')
    if not blocks:
        lines = text.splitlines()
        code_indices = [i for i, line in enumerate(lines) if CODE_LINE.search(line)]
        if code_indices:
            first = code_indices[0]
            # Keep code continuation lines and leave natural-language instructions outside it.
            source, prose = [], []
            for i, line in enumerate(lines):
                if i >= first and (CODE_LINE.search(line) or not re.search(r'[\u4e00-\u9fff]', line)):
                    source.append(line)
                else:
                    prose.append(line)
            blocks = ['\n'.join(source).strip()]; narrative = '\n'.join(prose)
    narrative = narrative.strip()
    probe = narrative.lower()
    similar = bool(re.search(r'(?:相似|类似|同类).{0,8}(?:代码|实现|逻辑)|(?:代码|实现|逻辑).{0,8}(?:相似|类似)|'
        r'(?:找|有没|有无|寻找).{0,5}(?:相似|类似)|同样.{0,5}(?:逻辑|实现)|similar\s+(?:code|implementation)|equivalent', probe)
        or (blocks and re.search(r'相似|类似|similar', probe))) and not bool(re.search(r'不(?:要|用|找).{0,3}(?:相似|类似)', probe))
    locating = bool(re.search(r'原(?:始)?(?:代码|实现)|出自|出处|来源|定位|(?:哪|哪里|在哪|何处).{0,8}(?:文件|程序|实现|代码)|(?:代码|实现).{0,8}(?:在哪|哪里)|find.{0,8}(?:source|original)', probe))
    explaining = bool(re.search(r'解释|含义|说明|做什么|为什么|如何|怎么|业务|explain', probe))
    mode = 'similar' if similar else 'source' if locating or (blocks and not explaining) else 'business'
    language = next((lang for lang in languages if lang), '')
    code = '\n\n'.join(blocks)
    if not language and code:
        language = 'cobol' if re.search(r'\b(?:MOVE|PERFORM|PIC|PROGRAM-ID|DIVISION)\b', code, re.I) else 'code'
    if not code and history and not re.search(r'\b[\w-]+\.(?:cbl|cob|cpy)\b', text, re.I) and re.search(r'它|该|上述|这个|继续|那|呢', text):
        previous = parse_query(history[-1].get('question', ''))
        if previous.code:
            return QueryPlan('similar' if similar else previous.mode, narrative, previous.code, previous.language, True)
    return QueryPlan(mode, narrative, code, language)


TOKEN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\d+(?:\.\d+)?|[A-Za-z][\w-]*|<=|>=|<>|!=|[<>=+*/().,:;-]", re.I)


def code_tokens(text):
    lines = []
    for line in text.splitlines():
        fixed = (len(line) > 6 and not line[:6].strip(' 0123456789') and
                 (line[6] in ' */-' or line[6] in 'Dd' and line[7:8].isspace()))
        if fixed:
            if line[6] in '*/':
                continue
            line = line[7:72]
        # Strip inline comments outside quoted strings only.
        quoted = False; quote = ''; output = ''
        i = 0
        while i < len(line):
            c = line[i]
            if not quoted and line[i:i + 2] == '*>':
                break
            if c in "\"'":
                if quoted and quote == c:
                    if i + 1 < len(line) and line[i + 1] == c:
                        output += c + c; i += 2; continue
                    quoted = False
                elif not quoted:
                    quoted = True; quote = c
            output += c; i += 1
        lines.append(output)
    return tuple(token if token.startswith(("'", '"')) else token.upper() for token in TOKEN.findall('\n'.join(lines)))


def code_match(query, text):
    """Preserve literals/operators for identity; structural similarity is a separate relation."""
    needle, haystack = code_tokens(query), code_tokens(text)
    if len(needle) < 3:
        return '', 0.0
    if find_tokens(haystack, needle) is not None:
        return 'exact_source', 1.0
    keywords = {'IF', 'ELSE', 'END-IF', 'MOVE', 'TO', 'CALL', 'USING', 'PERFORM', 'COMPUTE', 'ADD', 'SUBTRACT', 'FROM', 'GOBACK', 'READ', 'WRITE', 'INTO', 'END-READ', 'DISPLAY', 'END-CALL'}
    def structural(tokens):
        return tuple(t if t in keywords or not re.match(r'^[A-Z][\w-]*$', t) else 'ID' for t in tokens)
    def shingles(tokens):
        return {tokens[i:i + 3] for i in range(max(0, len(tokens) - 2))}
    left, right = shingles(structural(needle)), shingles(structural(haystack))
    similarity = len(left & right) / max(1, len(left | right))
    return ('similar_logic', similarity) if similarity >= .25 else ('', similarity)


def find_tokens(haystack, needle):
    """Linear subsequence matching, preserving token/literal boundaries."""
    if not needle:
        return None
    prefix = [0] * len(needle)
    matched = 0
    for i in range(1, len(needle)):
        while matched and needle[i] != needle[matched]:
            matched = prefix[matched - 1]
        if needle[i] == needle[matched]:
            matched += 1
        prefix[i] = matched
    matched = 0
    for i, token in enumerate(haystack):
        while matched and token != needle[matched]:
            matched = prefix[matched - 1]
        if token == needle[matched]:
            matched += 1
        if matched == len(needle):
            return i - len(needle) + 1
    return None
