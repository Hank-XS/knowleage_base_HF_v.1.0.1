"""Audit/build a data-free worktree snapshot without touching local data or Git history."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[2]
DATA_READMES = {'backend/data/README.md', 'hf_data/README.md'}
LOCAL_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
              '.mypy_cache', '.ruff_cache', '.pnpm-store', '.turbo', '.cache', '.local',
              '.local-runtime', '.local-tools', '.codegraph', 'dist', 'dist-ssr',
              'coverage', 'test-results', 'playwright-report', 'blob-report', 'htmlcov',
              'release', 'artifacts', '.nitro', '.output', 'dev-dist'}
ARTIFACT_SUFFIXES = {'.zip', '.tar', '.tgz', '.gz', '.7z', '.rar', '.war', '.db', '.sqlite',
                     '.sqlite3', '.duckdb', '.pyc', '.pyo', '.log', '.pem', '.key', '.pfx', '.p12',
                     '.safetensors', '.ckpt', '.pt', '.pth', '.onnx'}
LOCAL_DATA_FILES = {'backend/scripts/qa_cases.json'}
PUBLIC_ENV_NAMES = {'.env.development', '.env.production', '.env.analyze'}
ROOT_FILES = {'.gitignore', '.gitattributes', 'README.md', 'docker-compose.yml', 'start.bat', 'LICENSE'}
SOURCE_DIRS = {'backend', 'frontend', 'docs', 'mcp', 'hf_data'}
SECRET_RULES = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b'),
    'api-token': re.compile(rb'\b(?:sk-[A-Za-z0-9_-]{24,}|npm_[A-Za-z0-9]{30,})\b'),
    'aws-access-key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
}
ENV_SECRET = re.compile(r'^[ \t]*(?:KB_LLM_API_KEY|KB_EMB_API_KEY|GITHUB_TOKEN|GH_TOKEN|OPENAI_API_KEY|NPM_TOKEN)[ \t]*=[ \t]*([^\r\n]*)', re.M)


def git_paths(*args):
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z', *args], check=True, capture_output=True)
    return {value.decode('utf-8') for value in result.stdout.split(b'\0') if value}


def exclusion(path):
    """Same policy for tracked paths and newly created source; never trust ignores alone."""
    if path in DATA_READMES:
        return ''
    parts = PurePosixPath(path).parts
    if not parts or any(part in {'..', ''} for part in parts):
        return 'invalid-path'
    if path in LOCAL_DATA_FILES or path.startswith(('backend/data/', 'hf_data/', 'backend/tests/fixtures/')):
        return 'data-or-fixture'
    if any(part in LOCAL_DIRS for part in parts[:-1]):
        return 'local-or-generated'
    name = parts[-1]
    if name == '.env' or name.startswith('.env.'):
        if name == '.env.example':
            return ''
        if parts[0] == 'frontend' and name in PUBLIC_ENV_NAMES:
            return ''
        return 'private-env'
    if (PurePosixPath(name).suffix.lower() in ARTIFACT_SUFFIXES or name.endswith(('-wal', '-shm', '.tsbuildinfo'))
            or name in {'.coverage', '.eslintcache', '.stylelintcache'}):
        return 'artifact-or-private-key'
    if len(parts) == 1 and name not in ROOT_FILES:
        return 'non-source-root-file'
    if len(parts) > 1 and parts[0] not in SOURCE_DIRS:
        return 'non-source-directory'
    return ''


def scan_secrets(path, content):
    findings = []
    for rule, pattern in SECRET_RULES.items():
        for match in pattern.finditer(content):
            findings.append(dict(path=path, line=content[:match.start()].count(b'\n') + 1, rule=rule))
    text = content.decode('utf-8', errors='replace')
    for match in ENV_SECRET.finditer(text):
        value = match[1].strip(' \t\"\'')
        if value and not re.search(r'YOUR|PLACEHOLDER|CHANGEME|CHANGE-ME|你的|<|示例', value, re.I):
            findings.append(dict(path=path, line=text[:match.start()].count('\n') + 1, rule='configured-env-secret'))
    return findings


def collect():
    tracked = git_paths('--cached')
    candidates = tracked | git_paths('--others', '--exclude-standard')
    selected, excluded, findings = [], [], []
    for relative in sorted(candidates):
        reason = exclusion(relative)
        path = ROOT / relative
        if reason:
            excluded.append(dict(path=relative, reason=reason, tracked=relative in tracked))
            continue
        if not path.exists():
            continue  # Preserve intentional source deletions in the worktree snapshot.
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError(f'Refusing symlink/outside path: {relative}')
        if not path.is_file():
            continue
        content = path.read_bytes()
        findings.extend(scan_secrets(relative, content))
        selected.append(dict(path=relative, size=len(content), sha256=hashlib.sha256(content).hexdigest()))
    return selected, excluded, findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Build a ZIP from current source; defaults to audit only')
    parser.add_argument('--report', type=Path, help='Optional audit report (keep under a local/ignored directory)')
    parser.add_argument('--untrack-list', type=Path, help='Write excluded tracked paths as NUL-separated UTF-8; does not change Git')
    args = parser.parse_args()
    selected, excluded, findings = collect()
    result = dict(source_files=len(selected), source_bytes=sum(row['size'] for row in selected),
                  excluded_tracked=sum(row['tracked'] for row in excluded), secret_findings=findings,
                  excluded=excluded, files=selected)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    if args.untrack_list:
        args.untrack_list.parent.mkdir(parents=True, exist_ok=True)
        args.untrack_list.write_bytes(b''.join(row['path'].encode('utf-8') + b'\0' for row in excluded if row['tracked']))
    if findings:
        print(json.dumps(dict(status='blocked', findings=findings), ensure_ascii=True, indent=2))
        raise SystemExit(2)
    if args.output:
        output = args.output.resolve()
        if output.is_relative_to(ROOT) and not exclusion(output.relative_to(ROOT).as_posix()):
            raise SystemExit('Archive must be outside the repository or in an ignored artifact directory')
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for row in selected:
                content = (ROOT / row['path']).read_bytes()
                if hashlib.sha256(content).hexdigest() != row['sha256']:
                    raise RuntimeError(f'Source changed during export: {row["path"]}; rerun export')
                archive.writestr('knowledge-base/' + row['path'], content)
        with zipfile.ZipFile(output) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(selected)
            assert all(not exclusion(name.removeprefix('knowledge-base/')) for name in archive.namelist())
        result['archive'] = str(output)
        result['archive_bytes'] = output.stat().st_size
        result['archive_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in {'files', 'excluded'}}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
