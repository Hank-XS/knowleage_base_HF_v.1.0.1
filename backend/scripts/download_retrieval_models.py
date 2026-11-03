"""Download explicit, revision-pinned public retrieval weights into the workspace."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fnmatch
import json
from pathlib import Path
import time
import httpx


def download(repo, target, pinned_revision=''):
    target.mkdir(parents=True, exist_ok=True)
    if (target / 'hf-revision.json').is_file() and (target / 'model.safetensors').is_file():
        print(f'{repo}: already downloaded',flush=True)
        return
    for attempt in range(0 if pinned_revision else 5):
        try:
            with httpx.Client(follow_redirects=True, timeout=45, trust_env=attempt % 2 == 0) as client:
                response = client.get('https://huggingface.co/api/models/' + repo)
                response.raise_for_status(); info = response.json()
            break
        except httpx.HTTPError:
            if attempt == 4:
                raise
            time.sleep(attempt + 1)
    if pinned_revision:
        info = dict(sha=pinned_revision, siblings=[dict(rfilename=name) for name in
            ('config.json','generation_config.json','merges.txt','model.safetensors','tokenizer.json','tokenizer_config.json','vocab.json')])
    revision = info['sha']
    patterns = ['*.json', '*.safetensors', 'vocab.txt', 'merges.txt', '*.model']
    names = [s['rfilename'] for s in info['siblings'] if any(fnmatch.fnmatch(s['rfilename'], p) for p in patterns)
             and not any(part in s['rfilename'].split('/') for part in ('onnx', 'openvino', 'onnx-int8'))]
    def fetch(name):
        path = (target / name).resolve()
        if not path.is_relative_to(target.resolve()):
            raise ValueError('Invalid model file path')
        path.parent.mkdir(parents=True, exist_ok=True)
        marker = path.with_name(path.name + '.revision')
        if path.is_file() and marker.is_file() and marker.read_text() == revision:
            return
        last_error = None
        for attempt in range(3):
            try:
                with httpx.Client(follow_redirects=True, timeout=180, trust_env=attempt % 2 == 0) as client:
                    with client.stream('GET', f'https://huggingface.co/{repo}/resolve/{revision}/{name}') as result:
                        result.raise_for_status()
                        partial = path.with_name(path.name + '.partial')
                        with partial.open('wb') as output:
                            for block in result.iter_bytes(1024 * 1024):
                                output.write(block)
                        partial.replace(path)
                        marker.write_text(revision)
                        print(f'{repo}: {name} ({path.stat().st_size} bytes)', flush=True)
                return
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc; time.sleep(attempt + 1)
        raise last_error
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, names))
    (target / 'hf-revision.json').write_text(json.dumps(dict(repo=repo, revision=revision)), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1] / '.local/models')
    parser.add_argument('--reranker-revision', default='')
    args = parser.parse_args()
    for kind in ('Embedding', 'Reranker'):
        repo = f'Qwen/Qwen3-{kind}-0.6B'
        download(repo, args.root / repo.split('/')[-1], args.reranker_revision if kind == 'Reranker' else '')
