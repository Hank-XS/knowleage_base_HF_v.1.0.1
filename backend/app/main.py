"""FastAPI 主应用：trace_id 中间件 + 统一响应/异常 + 路由装配 + 启动种子。"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import init_db
from .response import KbError, err
from .routers import auth, governance, ingest, knowledge, misc, qa

app = FastAPI(title=settings.app_name, version="1.0.0-demo",
              docs_url="/docs", openapi_url="/openapi.json")

app.add_middleware(
    CORSMiddleware,
    # 局域网 IP / 多入口访问时放宽；鉴权走 Authorization header，不依赖 cookie
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    request.state.trace_id = request.headers.get("X-Trace-Id") or f"tr_{uuid.uuid4().hex[:10]}"
    resp = await call_next(request)
    resp.headers["X-Trace-Id"] = request.state.trace_id
    # Checkmarx Missing_HSTS：须为单行 header 值
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.exception_handler(KbError)
async def kb_error_handler(request: Request, exc: KbError):
    return JSONResponse(status_code=exc.http, content=err(exc.code, exc.message, request))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content=err("40001", str(exc.errors()[:3]), request))


@app.exception_handler(Exception)
async def fallback_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content=err("50001", f"{type(exc).__name__}: {exc}", request))


P = settings.api_prefix
app.include_router(auth.router, prefix=P)
app.include_router(qa.router, prefix=P)
app.include_router(qa.search_router, prefix=P)
app.include_router(governance.router, prefix=P)
app.include_router(ingest.router, prefix=P)
app.include_router(knowledge.router, prefix=P)
app.include_router(misc.router, prefix=P)


@app.post(f"{P}/ingest/seed", tags=["ingest"])
def seed_endpoint(force: bool = False):
    from .seed import seed_knowledge
    return seed_knowledge(force=force)


@app.on_event("startup")
def startup() -> None:
    init_db()
    from .ingest.tagger import ensure_vocab
    from .prompt_config import ensure_prompt_defaults
    from .seed import seed_knowledge, seed_users
    seed_users()
    ensure_vocab()
    ensure_prompt_defaults()
    seed_knowledge()
    try:
        from .knowledge.manage import ensure_synced
        ensure_synced()
    except Exception:
        # 数据集缺失时不阻断启动
        pass
