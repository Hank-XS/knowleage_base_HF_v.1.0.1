"""Explicit offline build. Stop the API before activation to avoid cross-process writers."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-model', default='')
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--rollback', default='')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--activate', default='')
    args = parser.parse_args()
    from app.config import settings
    if args.local_model:
        settings.kb_emb_local_path = str(Path(args.local_model).resolve())
        settings.kb_model_device = args.device
    from app.knowledge.indexing import rebuild, rollback, activate
    from app.llm import get_embedder
    from app.stores.vector import vector_store
    if args.rollback:
        report = rollback(vector_store,args.rollback)
    elif args.activate:
        report = activate(vector_store,args.activate)
    else:
        report = rebuild(vector_store,get_embedder(),lambda r:print(json.dumps(r),flush=True), stage_only=args.stage_only)
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__ == '__main__':
    main()
