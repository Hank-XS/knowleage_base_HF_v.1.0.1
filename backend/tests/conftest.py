"""Tests generate their own material and never load the application's data directory."""
import atexit
import json
import os
from pathlib import Path
import shutil
import tempfile

import pytest


_test_data = Path(tempfile.mkdtemp(prefix='hf-tests-')).resolve()
os.environ['KB_DATA_DIR'] = str(_test_data)
for _setting in ('KB_PG_DSN', 'KB_GRAPH_URL', 'KB_VECTOR_URI', 'KB_S3_ENDPOINT',
                 'KB_LLM_API_KEY', 'DEEPSEEK_API_KEY', 'KB_EMB_API_KEY', 'KB_EMB_BASE_URL',
                 'KB_EMB_LOCAL_PATH', 'KB_RERANK_LOCAL_PATH', 'KB_RERANK_URL'):
    os.environ[_setting] = ''
os.environ['KB_AUTO_IMPORT'] = 'false'
os.environ['KB_DATASET_ROOT'] = str(_test_data / 'missing-dataset')


def _remove_test_data():
    if _test_data.parent == Path(tempfile.gettempdir()).resolve() and _test_data.name.startswith('hf-tests-'):
        shutil.rmtree(_test_data, ignore_errors=True)


atexit.register(_remove_test_data)


@pytest.fixture
def sample_seed(tmp_path, monkeypatch):
    from app import seed
    from app.ingest import pipeline
    from app.qa import source_view
    from app.tools import handlers

    root = tmp_path / 'seed'

    def write(relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    write('error_codes/errors.csv', 'code,meaning,action,level,process\n' + ''.join(
        f'{i},余额不足,检查账户余额,error,余额校验\n' for i in range(10, 18)))
    write('mapping/fields.csv', 'src_system,src_field,dst_system,dst_field,rule,business_key\n'
          'old,AMOUNT,new,amount,直传,withdraw\n')
    write('messages/response.json', json.dumps({
        'name': 'withdraw-response', 'fields': [{'name': 'STATUS', 'type': 'X', 'length': 2}],
    }))
    for name in ('atm_withdraw_flow', 'atm_balance_flow'):
        write(f'docs/{name}.md', '# ATM取款流程\n\nATMWD402 执行取款和余额校验。错误码14表示余额不足。\n'
              '## 处理建议\n检查账户余额和交易金额。\n## 依据\nBALCHK100 执行余额校验。\n')
    write('cobol/ATMWD402.cbl', '       IDENTIFICATION DIVISION.\n       PROGRAM-ID. ATMWD402.\n'
          '       PROCEDURE DIVISION.\n' + ''.join(
              f'       {name} SECTION.\n           PERFORM BALCHK100.\n'
              for name in ('4000-MAIN', '4010-INPUT', '4020-CHECK-BAL', '4030-CHECK-LIMIT', '4040-POST')))
    monkeypatch.setattr(seed, 'SEED_DIR', root)
    monkeypatch.setattr(source_view, 'SEED_DIR', root)
    for module in (source_view, handlers):
        monkeypatch.setattr(module, 'graph_store', seed.graph_store)
        monkeypatch.setattr(module, 'vector_store', pipeline.vector_store)
    return root


@pytest.fixture
def sample_dataset(tmp_path, monkeypatch):
    from app.config import settings

    root = tmp_path / 'dataset'
    code = root / '02_code_assets' / 'github_cobol'
    code.mkdir(parents=True)
    for i in range(60):
        (code / f'TEST{i:03d}.cbl').write_text(
            f'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST{i:03d}.\n'
            '       PROCEDURE DIVISION.\n       MAIN-LOGIC.\n           GOBACK.\n', encoding='utf-8')
    (code / 'FIX_TMP_EXAMPLE.cbl').write_text('       PROGRAM-ID. OLD-PROGRAM.\n', encoding='utf-8')
    docs = root / '01_tech_docs'
    docs.mkdir()
    (docs / 'guide.md').write_text('# Test guide\n\nSynthetic material for ingestion tests.\n', encoding='utf-8')
    monkeypatch.setattr(settings, 'kb_dataset_root', str(root))
    return root
