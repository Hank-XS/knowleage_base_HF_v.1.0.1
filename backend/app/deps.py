"""鉴权（JWT + RBAC 五角色）与审计（设计 9.2 节）。"""
from __future__ import annotations

import hashlib
import hmac

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from .config import settings
from .db import AuditLog, SessionLocal, User
from .response import KbError

_bearer = HTTPBearer(auto_error=False)

ROLES = ("dev", "biz", "arch", "gov", "admin")
ROLE_NAMES = {"dev": "研发", "biz": "业务", "arch": "架构", "gov": "治理员", "admin": "管理员"}


def hash_password(pwd: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), pwd.encode(), hashlib.sha256).hexdigest()


def verify_password(pwd: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(pwd), hashed)


def issue_token(user: User) -> str:
    payload = {"sub": user.username, "role": user.role, "name": user.display_name}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(request: Request,
                 cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if cred is None:
        raise KbError("40101")
    try:
        payload = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise KbError("40101")
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == payload["sub"])).scalar_one_or_none()
    if user is None:
        raise KbError("40101")
    request.state.actor = user.username
    return user


def require_roles(*roles: str):
    def _dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise KbError("40301")
        return user
    return _dep


def audit(request: Request, actor: str, action: str, obj: str = "", detail: dict | None = None) -> None:
    with SessionLocal() as db:
        db.add(AuditLog(actor=actor, action=action, object=obj[:128],
                        detail=detail or {}, trace_id=getattr(request.state, "trace_id", "-")))
        db.commit()
