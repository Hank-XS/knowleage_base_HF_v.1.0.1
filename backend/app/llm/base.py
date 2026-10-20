"""LLM / Embedding / Reranker 抽象与工厂。

- ApiLLM / ApiEmbedder：OpenAI 兼容接口（GLM、DeepSeek、Qwen、vLLM 本地服务均可）。
- MockLLM：无 Key 时基于检索证据的确定性模板作答，保证全链路可演示。
- HashEmbedder：无 Embedding 服务时的确定性哈希向量（演示用，接真实模型后自动替换）。
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Protocol

import httpx

from ..config import settings


class ChatLLM(Protocol):
    name: str

    def chat(self, messages: list[dict], *, temperature: float = 0.2, json_mode: bool = False) -> str: ...


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


# ---------------------------------------------------------------- api llm
class ApiLLM:
    def __init__(self) -> None:
        self.name = f"api:{settings.kb_llm_model}"

    def chat(self, messages: list[dict], *, temperature: float = 0.2, json_mode: bool = False) -> str:
        body: dict = {"model": settings.kb_llm_model, "messages": messages, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = httpx.post(
            f"{settings.kb_llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.kb_llm_api_key}"},
            json=body, timeout=settings.kb_llm_timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def chat_tools(
        self,
        messages: list[dict],
        *,
        tools: list[dict],
        temperature: float = 0.1,
        tool_choice: str | dict = "auto",
    ) -> dict:
        """OpenAI 兼容 function/tool calling，返回 message 字典（含 tool_calls）。"""
        body: dict = {
            "model": settings.kb_llm_model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        resp = httpx.post(
            f"{settings.kb_llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.kb_llm_api_key}"},
            json=body, timeout=settings.kb_llm_timeout,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        return {
            "role": msg.get("role", "assistant"),
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }


class ApiEmbedder:
    def __init__(self) -> None:
        base = settings.kb_emb_base_url or settings.kb_llm_base_url
        key = settings.kb_emb_api_key or settings.kb_llm_api_key
        self._base, self._key = base, key
        self.name = f"api:{settings.kb_emb_model}"
        self.dim = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 16):  # 小批量，避免超长请求
            batch = texts[i:i + 16]
            resp = httpx.post(
                f"{self._base.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": settings.kb_emb_model, "input": batch},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            out.extend(d["embedding"] for d in data)
        self.dim = len(out[0]) if out else 0
        return out


class ApiReranker:
    """TEI 风格 /rerank 端点（可选）。"""

    def __init__(self) -> None:
        self.name = f"tei:{settings.kb_rerank_url}"

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        resp = httpx.post(
            settings.kb_rerank_url.rstrip("/") + "/rerank",
            json={"query": query, "texts": documents}, timeout=30.0,
        )
        resp.raise_for_status()
        return [float(x) for x in resp.json()]


# ---------------------------------------------------------------- fallbacks
class MockLLM:
    """无 API Key 时的确定性作答：从检索证据拼装三段式答案（演示与联调用）。"""

    def __init__(self) -> None:
        self.name = "mock:template"

    def chat(self, messages: list[dict], *, temperature: float = 0.2, json_mode: bool = False) -> str:
        # 约定：system 之后第一条 user 消息携带 __evidence__ 摘要时走模板；否则通用回复
        for m in messages:
            if m["role"] == "user" and m["content"].startswith("{") and '"__mock_qa__"' in m["content"]:
                payload = json.loads(m["content"])
                answer = _mock_answer(payload)
                return json.dumps(answer, ensure_ascii=False) if json_mode else json.dumps(answer, ensure_ascii=False, indent=2)
        return "【MockLLM】当前未配置大模型 API Key。请在 backend/.env 中填写 KB_LLM_API_KEY 等配置以启用真实模型。"


def _mock_answer(payload: dict) -> dict:
    ev: list[dict] = payload.get("evidence", [])
    question: str = payload.get("question", "")
    what, why_lines, how_lines = "", [], []
    for i, e in enumerate(ev, start=1):
        label = e.get("label") or e.get("ref") or f"证据{i}"
        text = (e.get("text") or "")[:180]
        if i == 1:
            what = f"依据知识库［{i}］：{label}。{text}" if text else f"知识库中与该问题最相关的对象是 {label}。"
        why_lines.append(f"［{i}］{label}：{text}")
    if not ev:
        what = "知识库未覆盖该问题（当前为 Mock 模式且检索无证据）。"
        why_lines.append("多路检索未返回相关证据，请确认知识是否已接入。")
    how_lines.append("按证据链路逐条核对：先确认业务口径，再核对报文/字段映射，最后定位代码单元。")
    how_lines.append("涉及业务规则的结论需人工复核后方可用于变更。")
    return {
        "what": what,
        "why": "\n".join(why_lines),
        "how": "\n".join(how_lines),
        "caveats": ["Mock 模式答案为证据模板拼接，配置真实 LLM 后将由模型综合分析生成"],
        "confidence": 0.55,
        "uncovered": not ev,
    }


class HashEmbedder:
    """确定性字符 n-gram 哈希向量：无 Embedding 服务时的演示实现。"""

    def __init__(self, dim: int = 256) -> None:
        self.name = "hash:ngram"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        t = "".join(text.lower().split())
        for i in range(len(t) - 1):
            g = t[i:i + 2]
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vec[h] += 1.0
        if t:
            h = int(hashlib.md5(t[:24].encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vec[h] += 0.5
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [round(x / norm, 6) for x in vec]


# ---------------------------------------------------------------- factory
_llm: ChatLLM | None = None
_emb: Embedder | None = None
_rr: Reranker | None = None


def get_llm() -> ChatLLM:
    global _llm
    if _llm is None:
        _llm = ApiLLM() if settings.kb_llm_api_key else MockLLM()
    return _llm


def get_embedder() -> Embedder:
    """仅当显式配置 KB_EMB_BASE_URL 时走 API 向量（如豆包/智谱）；
    DeepSeek 等无 embedding 接口的 provider 不能只凭 LLM Key 启用。"""
    global _emb
    if _emb is None:
        if settings.kb_emb_base_url:
            _emb = ApiEmbedder()
        else:
            _emb = HashEmbedder()
    return _emb


def get_reranker() -> Reranker | None:
    global _rr
    if _rr is None and settings.kb_rerank_url:
        _rr = ApiReranker()
    return _rr


def llm_status() -> dict:
    llm, emb, rr = get_llm(), get_embedder(), get_reranker()
    return {
        "llm": {"mode": "api" if isinstance(llm, ApiLLM) else "mock", "name": llm.name,
                "model": settings.kb_llm_model if isinstance(llm, ApiLLM) else None},
        "embedding": {"mode": "api" if isinstance(emb, ApiEmbedder) else "hash", "name": emb.name,
                      "model": settings.kb_emb_model if isinstance(emb, ApiEmbedder) else None},
        "rerank": {"mode": "api" if rr else "heuristic", "name": rr.name if rr else "heuristic:keyword"},
        "hint": "" if isinstance(llm, ApiLLM) else "未配置 KB_LLM_API_KEY，当前为 Mock 模式；在 backend/.env 填写后重启即可启用真实模型。",
    }
