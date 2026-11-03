"""Source-grounded retrieval benchmark. Generated origin cases are not a human blind test."""
import argparse
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'.local/retrieval-cases.json')
    parser.add_argument('--create-cases',action='store_true')
    parser.add_argument('--index',type=Path)
    parser.add_argument('--local-model',default='')
    parser.add_argument('--reranker-model',default='')
    parser.add_argument('--kind',choices=['source','business'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.create_cases and not args.cases.is_file():
        parser.error('Supply --cases with your own questions, or use --create-cases to generate source-origin cases')
    source_root=ROOT/'data'
    with tempfile.TemporaryDirectory(prefix='hf-retrieval-bench-') as temporary:
        target=Path(temporary)
        with closing(sqlite3.connect((source_root/'kb.sqlite3').as_uri()+'?mode=ro',uri=True)) as src:
            with closing(sqlite3.connect(target/'kb.sqlite3')) as dest:src.backup(dest)
        (target/'runtime').mkdir()
        for name in ('graph_store.json','vector_store.json'):
            if (source_root/'runtime'/name).exists():shutil.copy2(source_root/'runtime'/name,target/'runtime'/name)
        if args.index:shutil.copy2(args.index,target/'runtime/vector_store.json')
        import os
        os.environ['KB_DATA_DIR']=str(target)
        os.environ['KB_PG_DSN']='';os.environ['KB_GRAPH_URL']='';os.environ['KB_VECTOR_URI']=''
        from app.config import settings
        settings.kb_emb_local_path=str(Path(args.local_model).resolve()) if args.local_model else ''
        settings.kb_emb_base_url='';settings.kb_rerank_local_path=str(Path(args.reranker_model).resolve()) if args.reranker_model else '';settings.kb_rerank_url=''
        settings.kb_rerank_enabled=bool(args.reranker_model)
        if args.create_cases:
            from app.knowledge.query_parser import code_tokens,find_tokens
            with closing(sqlite3.connect(target/'kb.sqlite3')) as db:
                sources=db.execute('SELECT d.source_path,v.content FROM t_kb_document d JOIN t_kb_doc_version v ON v.doc_id=d.id AND v.version=d.version WHERE d.is_current=1 AND d.vectorized=1 AND d.asset_type=\'code\'').fetchall()
            cases=[]
            sequences={path:code_tokens(body) for path,body in sources}
            seen=set()
            for path,body in sources:
                lines=body.splitlines(keepends=True)
                count=0
                for first in range(0,len(lines),5):
                    snippet=''.join(lines[first:first+6]).strip('\n'); tokens=code_tokens(snippet)
                    if len(tokens)<10 or tokens in seen:continue
                    paths=[p for p,other in sequences.items() if find_tokens(other,tokens) is not None]
                    if len(paths)!=1:continue
                    seen.add(tokens);count+=1
                    cases.append(dict(id=f'origin-{len(cases)}',kind='source',question='这段代码出自哪个文件？\n```cobol\n'+snippet+'\n```',expected_paths=paths,annotation='deterministic-source-span'))
                    if count>=3 or len(cases)>=200:break
                if len(cases)>=200:break
            args.cases.parent.mkdir(parents=True,exist_ok=True)
            args.cases.write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
        cases=json.loads(args.cases.read_text('utf-8'))
        if args.kind:cases=[case for case in cases if case['kind']==args.kind]
        if not cases:
            parser.error('No matching cases; import source material or supply your own annotated questions')
        from app.knowledge import retrieval
        from app.knowledge.scope import question_scoped
        from app.qa.flow import SessionContext
        from app.knowledge.query_parser import parse_query
        class Runner:
            @question_scoped
            def run(self,ctx):
                return retrieval.retrieve(ctx.question,'business_rule',[],top_k=10)
        results=[]
        for case in cases:
            start=time.monotonic()
            hits=Runner().run(SessionContext('benchmark',question=case['question'],role='admin'))
            paths=[]
            for hit in hits:
                p=hit.get('path') or hit.get('obj','')
                if p and p not in paths:paths.append(p)
            rank=next((i+1 for i,p in enumerate(paths) if p in case['expected_paths']),None)
            results.append(dict(id=case['id'],kind=case['kind'],rank=rank,paths=paths,elapsed_ms=round((time.monotonic()-start)*1000)))
            print(f'{case["id"]}: rank={rank}',flush=True)
        grouped=defaultdict(list)
        for result in results:grouped[result['kind']].append(result)
        metrics={kind:dict(count=len(rows),top1=sum(r['rank']==1 for r in rows)/len(rows),
            top5=sum(r['rank'] is not None and r['rank']<=5 for r in rows)/len(rows),
            top10=sum(r['rank'] is not None and r['rank']<=10 for r in rows)/len(rows),
            mrr=sum(1/r['rank'] if r['rank'] else 0 for r in rows)/len(rows)) for kind,rows in grouped.items()}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(metrics=metrics,results=results,limitations='Generated origin cases are not a human blind test; business relevance depends on user-supplied annotations; no equivalence claim.'),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(metrics),flush=True)
        from app.db import engine
        engine.dispose()


if __name__=='__main__':main()
