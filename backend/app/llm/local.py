"""Optional, explicitly downloaded local retrieval models; never downloads on a request."""
import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path
import sqlite3
from threading import RLock

from ..config import DATA_DIR, settings


def contract(path, kind):
    root = Path(path)
    manifest = root / 'hf-revision.json'
    revision = manifest.read_text('utf-8') if manifest.exists() else str(root.resolve())
    digest = hashlib.sha256(f'{kind}|{revision}|{settings.kb_emb_query_instruction}|normalized-v2'.encode()).hexdigest()[:16]
    return f'local:{root.name}:{digest}'


class LocalEmbedder:
    def __init__(self):
        import torch
        torch.set_num_threads(settings.kb_model_cpu_threads)
        from sentence_transformers import SentenceTransformer
        self.name = contract(settings.kb_emb_local_path, 'embedding')
        self.model = SentenceTransformer(settings.kb_emb_local_path, device=settings.kb_model_device, local_files_only=True,
            model_kwargs={'torch_dtype':torch.float16 if settings.kb_model_device.startswith('cuda') else torch.float32})
        self.model.max_seq_length = 2048
        self.dim = self.model.get_sentence_embedding_dimension()
        self.tokenizer = self.model.tokenizer
        self._lock = RLock()
        self.cache = DATA_DIR / 'runtime' / 'embedding-cache.sqlite3'
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache) as db:
            db.execute('CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL)')

    def embed_queries(self, texts):
        return self._encode(texts, True)

    def embed(self, texts):
        return self._encode(texts, False)

    def _encode(self, texts, query):
        if not texts:
            return []
        inputs = [f'Instruct: {settings.kb_emb_query_instruction}\nQuery: {t}' if query else t for t in texts]
        keys = [hashlib.sha256((self.name + '\0' + text).encode()).hexdigest() for text in inputs]
        with self._lock, sqlite3.connect(self.cache) as db:
            cached = {key: json.loads(row[0]) for key in keys if (row := db.execute('SELECT vector FROM embeddings WHERE key=?', (key,)).fetchone())}
            missing = list(dict.fromkeys(key for key in keys if key not in cached))
            mapping = dict(zip(keys, inputs))
            if missing:
                vectors = self.model.encode([mapping[key] for key in missing], batch_size=settings.kb_retrieval_batch_size,
                    normalize_embeddings=True, show_progress_bar=False).tolist()
                from ..ingest.quality import validate_embeddings
                validate_embeddings(vectors, len(missing))
                for key, vector in zip(missing, vectors):
                    db.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?)', (key, json.dumps(vector)))
                    cached[key] = vector
            return [cached[key] for key in keys]


class LocalReranker:
    def __init__(self):
        import torch
        torch.set_num_threads(settings.kb_model_cpu_threads)
        from transformers import AutoTokenizer, AutoModelForCausalLM
        self.name = contract(settings.kb_rerank_local_path, f'reranker:bounded-v1:{settings.kb_rerank_max_tokens}')
        self.tokenizer = AutoTokenizer.from_pretrained(settings.kb_rerank_local_path, padding_side='left', local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(settings.kb_rerank_local_path, local_files_only=True,
            torch_dtype=torch.float16 if settings.kb_model_device.startswith('cuda') else torch.float32).to(settings.kb_model_device).eval()
        self.yes = self.tokenizer.convert_tokens_to_ids('yes')
        self.no = self.tokenizer.convert_tokens_to_ids('no')
        self.lock = RLock()
        self._scores = OrderedDict()
        prefix = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
        suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
        self._prefix = self.tokenizer.encode(prefix, add_special_tokens=False)
        self._suffix = self.tokenizer.encode(suffix, add_special_tokens=False)
        self._instruction = self.tokenizer.encode(f'<Instruct>: {settings.kb_emb_query_instruction}\n<Query>: ', add_special_tokens=False)
        self._document = self.tokenizer.encode('\n<Document>: ', add_special_tokens=False)
        self._omission = self.tokenizer.encode('\n[query excerpt omitted]\n', add_special_tokens=False)

    def rerank(self, query, documents):
        import torch
        if not documents:
            return []
        keys = [hashlib.sha256((self.name + '\0' + query + '\0' + doc).encode()).hexdigest() for doc in documents]
        texts = dict(zip(keys, documents))
        # Scores alone are cached. ACL/version filtering still runs before every lookup.
        with self.lock, torch.inference_mode():
            scores = {}
            for key in texts:
                if key in self._scores:
                    scores[key] = self._scores[key]
                    self._scores.move_to_end(key)
            missing = [key for key in texts if key not in scores]
            if missing:
                maximum = settings.kb_rerank_max_tokens
                query_ids = self.tokenizer.encode(query, add_special_tokens=False)
                query_limit = maximum // 3
                if len(query_ids) > query_limit:
                    # Keep the request and the end of a long code snippet; reserve document space.
                    content_limit = query_limit - len(self._omission)
                    if content_limit < 2:
                        raise ValueError('重排查询的输入预算不足')
                    head = content_limit // 2
                    query_ids = query_ids[:head] + self._omission + query_ids[-(content_limit - head):]
                prefix = self._prefix + self._instruction + query_ids + self._document
                doc_limit = maximum - len(prefix) - len(self._suffix)
                if doc_limit < 1:
                    raise ValueError('重排指令超过配置的输入预算')
                encoded = self.tokenizer([texts[key] for key in missing], padding=False, truncation=True,
                    max_length=doc_limit, add_special_tokens=False, return_attention_mask=False)['input_ids']
                inputs = [prefix + ids + self._suffix for ids in encoded]
                # Similar lengths in each batch reduce padding. Restore original order explicitly.
                order = sorted(range(len(inputs)), key=lambda i: len(inputs[i]))
                values = [0.0] * len(inputs)
                for begin in range(0, len(order), settings.kb_rerank_batch_size):
                    indices = order[begin:begin + settings.kb_rerank_batch_size]
                    batch = self.tokenizer.pad({'input_ids':[inputs[i] for i in indices]},
                        padding=True, return_tensors='pt').to(self.model.device)
                    logits = self.model(**batch, logits_to_keep=1).logits[:, -1, :]
                    probabilities = torch.softmax(logits[:, [self.no, self.yes]], dim=-1)[:, 1].cpu().tolist()
                    for i, value in zip(indices, probabilities):
                        values[i] = value
                if not all(math.isfinite(value) for value in values):
                    raise ValueError('重排模型返回非有限分数')
                scores.update(zip(missing, values))
                capacity = settings.kb_rerank_cache_size
                if capacity:
                    self._scores.update(zip(missing, values))
                    while len(self._scores) > capacity:
                        self._scores.popitem(last=False)
            return [scores[key] for key in keys]
