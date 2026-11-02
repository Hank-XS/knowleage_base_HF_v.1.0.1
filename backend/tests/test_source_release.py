"""The source export excludes material and artifacts while retaining runnable source."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('prepare_source', Path(__file__).resolve().parents[1] / 'scripts/prepare_source.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize('path', [
    'backend/data/kb.sqlite3', 'backend/data/runtime/graph_store.json',
    'backend/data/objects/kb-raw/projects/abc/source/TEST.cbl',
    'hf_data/08_cleaned/vector_chunks.jsonl', 'backend/.local/result.json',
    'backend/tests/fixtures/project/main.cbl', 'frontend/apps/web-antd/dist/index.html',
    'frontend/node_modules/package/index.js', 'backend/.env', 'backend/.env.production',
    'test-cobol.zip', 'report.docx', 'backend/tests/__pycache__/case.pyc',
])
def test_runtime_material_is_excluded(path):
    assert release.exclusion(path)


@pytest.mark.parametrize('path', [
    'backend/data/README.md', 'hf_data/README.md', 'backend/.env.example',
    'frontend/apps/web-antd/.env.development', 'frontend/apps/web-antd/.env.production',
    'frontend/apps/web-antd/src/views/kb/qa/index.vue', 'backend/app/knowledge/retrieval.py',
    'backend/tests/test_hybrid_retrieval.py', 'backend/tests/code_project_sample.py',
    'backend/tools/codegraph/package-lock.json', 'frontend/pnpm-lock.yaml', 'frontend/LICENSE',
])
def test_source_and_dependency_manifests_remain(path):
    assert not release.exclusion(path)


def test_secret_report_does_not_echo_secret_values():
    secret = ('ghp_' + 'A' * 36).encode()
    findings = release.scan_secrets('example.py', b'first line\n' + secret)
    assert findings == [dict(path='example.py', line=2, rule='github-token')]
    assert secret.decode() not in str(findings)
    assert not release.scan_secrets('backend/.env.example', b'KB_LLM_API_KEY=\n')
    assert not release.scan_secrets('backend/.env.example', b'KB_LLM_API_KEY=\nKB_LLM_MODEL=example-model\n')
