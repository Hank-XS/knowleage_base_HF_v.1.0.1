"""Evaluate real Flow/Agent against a local database snapshot; never writes live data.

Run from backend: python scripts/evaluate_qa.py --cases /path/to/private-qa-cases.json
Keyword gates are regression checks; human review is still required for factual accuracy.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True,
                        help='User-supplied evaluation questions; business samples are not bundled')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/qa-evaluation.json')
    parser.add_argument('--mode', choices=['flow', 'agent'], default='flow')
    parser.add_argument('--retrieval-only', action='store_true')
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    progress_path = args.output.with_suffix('.progress.jsonl')
    progress_path.write_text('', encoding='utf-8')
    original = Path(os.environ.get('KB_DATA_DIR', str(ROOT / 'data'))).resolve()
    with tempfile.TemporaryDirectory(prefix='hf-qa-eval-') as temp:
        target = Path(temp)
        # SQLite backup also sees committed WAL contents consistently.
        with closing(sqlite3.connect(f'{(original / "kb.sqlite3").as_uri()}?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(target / 'kb.sqlite3')) as dest:
                source.backup(dest)
        for name in ('runtime', 'objects'):
            if (original / name).exists():
                shutil.copytree(original / name, target / name)
        os.environ['KB_DATA_DIR'] = temp
        os.environ['KB_PG_DSN'] = ''
        os.environ['KB_GRAPH_URL'] = ''
        os.environ['KB_VECTOR_URI'] = ''
        os.environ['KB_S3_ENDPOINT'] = ''
        os.environ['KB_AUTO_IMPORT'] = 'false'
        from app.config import settings
        from app.llm.base import ApiLLM
        from app.qa.flow import SessionContext, flow
        from app.tools.agent import agent_flow
        from app.knowledge import retrieval
        from app.qa import analyzer
        report = dict(mode='retrieval' if args.retrieval_only else args.mode,
                      model=settings.kb_llm_model, results=[])
        if not args.retrieval_only:
            if not settings.kb_llm_api_key:
                report['blocked'] = 'No API key configured; refusing Mock evaluation'
            else:
                try:
                    ApiLLM().chat([{'role': 'user', 'content': 'Reply OK only.'}])
                except Exception as exc:
                    # Do not persist provider response bodies or credentials.
                    status = getattr(getattr(exc, 'response', None), 'status_code', None)
                    report['blocked'] = f'API preflight failed: {type(exc).__name__}, HTTP {status}'
        if 'blocked' not in report:
            for i, case in enumerate(cases):
                start = time.monotonic()
                row = dict(id=case['id'], question=case['question'])
                try:
                    if args.retrieval_only:
                        entities = analyzer.extract_entities(case['question'], case.get('history', []))
                        query = analyzer.rewrite_query(case['question'], entities, case.get('history', []))
                        hits = retrieval.retrieve(query, analyzer.classify_intent(case['question']), entities)
                        row['evidence'] = hits
                        text = '\n'.join(h.get('text', '') for h in hits)
                        row['passed'] = all(t.lower() in text.lower() for t in case.get('evidence_terms', [])) and (bool(hits) if case.get('min_sources', 0) else True)
                    else:
                        ctx = SessionContext(session_id=f'eval-{i}', question=case['question'], history=case.get('history', []))
                        ac = (agent_flow if args.mode == 'agent' else flow).run(ctx)
                        row.update(answer=ac.answer, sources=ac.sources, trace=ac.reasoning_trace)
                        from app.db import QaMessage, SessionLocal
                        with SessionLocal() as evaluation_db:
                            saved = evaluation_db.get(QaMessage, ac.answer_id)
                            row['diagnostics'] = saved.payload_json.get('retrieval_diagnostics', []) if saved else []
                        text = json.dumps(ac.answer, ensure_ascii=False).lower()
                        citations = {int(n) for n in re.findall(r'[\[［](\d+)[\]］]', text)}
                        source_numbers = {s['no'] for s in ac.sources}
                        checks = dict(summary=bool(ac.answer.get('summary')),
                            expected_terms=all(t.lower() in text for t in case.get('expected_terms', [])),
                            forbidden_terms=all(t.lower() not in text for t in case.get('forbidden_terms', [])),
                            sources=len(ac.sources) >= case.get('min_sources', 0),
                            citations=citations <= source_numbers,
                            uncovered=ac.answer.get('uncovered') == case['uncovered'])
                        row.update(checks=checks, passed=all(checks.values()))
                except Exception as exc:
                    row.update(passed=False, error=type(exc).__name__)
                row['elapsed_ms'] = round((time.monotonic() - start) * 1000)
                report['results'].append(row)
                with progress_path.open('a', encoding='utf-8') as progress:
                    progress.write(json.dumps(row, ensure_ascii=False) + '\n')
                failures = [name for name, passed in row.get('checks', {}).items() if not passed]
                detail = f" ({', '.join(failures)})" if failures else ''
                print(f"{case['id']}: {'PASS' if row['passed'] else 'FAIL'}{detail}", flush=True)
        report['passed'] = sum(r['passed'] for r in report['results'])
        report['total'] = len(cases)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(report.get('blocked') or f"{report['passed']}/{report['total']} passed")
        print(args.output.resolve())
        from app.db import engine
        engine.dispose()
        return 0 if report['passed'] == len(cases) else 1


if __name__ == '__main__':
    sys.exit(main())
