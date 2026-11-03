"""Carry the user's scope through tool calls without trusting model query rewrites."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

from . import lexical


_active = ContextVar('qa_retrieval_scope', default=None)


@dataclass
class QuestionScope:
    question: str
    paths: set | None
    docs: list
    symbols: set = field(default_factory=set)
    evidence_paths: set = field(default_factory=set)
    plan: object = None
    diagnostics: list = field(default_factory=list)
    denied_paths: set = field(default_factory=set)
    rerank_cache: dict = field(default_factory=dict)

    def allows(self, path):
        return path not in self.denied_paths

    def learn(self, evidence):
        if evidence.get('channel') == 'code':
            self.evidence_paths.add(evidence.get('path') or evidence.get('obj'))
        if evidence.get('channel') == 'code' and (evidence.get('path') or evidence.get('obj')) in (self.paths or set()):
            self.symbols.update(lexical.identifiers(evidence.get('text', '') or evidence.get('snippet', '')))

    def related_definition(self, query, path, text, job=''):
        """A symbol observed in the requested source may resolve in that project's copybook."""
        from pathlib import PurePosixPath
        if PurePosixPath(path).suffix.lower() != '.cpy':
            return False
        projects = {d.project_job for d in self.docs if d.project_job}
        if projects and job not in projects and not any(f'/projects/{p}/' in path for p in projects):
            return False
        identifiers = lexical.identifiers(lexical.current_question(query)) & self.symbols
        identifiers -= {'PIC', 'COMP', 'CALL', 'EXIT', 'CONTINUE', 'MOVE', 'ADD', 'COMPUTE', 'USING', 'TO', 'VALUE', 'SECTION', 'DIVISION'}
        return bool(identifiers & lexical.identifiers(text))


def active_scope():
    return _active.get()


def question_scoped(method):
    @wraps(method)
    def wrapped(self, ctx, *args, **kwargs):
        if _active.get() is not None:
            return method(self, ctx, *args, **kwargs)
        from .hybrid import code_scope
        from . import retrieval
        from .catalog import current_project_jobs
        from .query_parser import parse_query
        question = ctx.question
        plan = parse_query(question, ctx.history)
        paths, docs = code_scope(question, retrieval.graph_store, current_project_jobs(), [])
        if paths is None and ctx.history:
            previous = ctx.history[-1].get('question', '')
            previous_paths, _ = code_scope(previous, retrieval.graph_store, current_project_jobs(), [])
            identifiers = lexical.identifiers(question)
            known_field = any(node['props'].get('source_path') in (previous_paths or set())
                              and node['props'].get('name', '').upper() in identifiers
                              for node in retrieval.graph_store.dump()['nodes'])
            if known_field or any(w in question for w in ('它', '该', '上述', '这个', '继续', '那', '呢')):
                question = previous + '\n' + question
                paths, docs = code_scope(question, retrieval.graph_store, current_project_jobs(), [])
        from .access import denied_paths
        denied = denied_paths(ctx.user, getattr(ctx, 'role', ''))
        docs = [d for d in docs if d.source_path not in denied]
        if paths is not None:
            paths -= denied
        token = _active.set(QuestionScope(question, paths, docs, plan=plan,
            denied_paths=denied))
        try:
            return method(self, ctx, *args, **kwargs)
        finally:
            _active.reset(token)
    return wrapped
