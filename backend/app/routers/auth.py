"""REST 路由：按设计第 7 章接口清单实现。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, User
from ..deps import audit, current_user, issue_token, verify_password
from ..response import KbError, ok

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, request: Request):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.pwd_hash):
        raise KbError("40101", "用户名或密码错误")
    audit(request, user.username, "login")
    token = issue_token(user)
    return ok({"token": token, "accessToken": token, "role": user.role,
               "display_name": user.display_name,
               "expires_in": settings.jwt_expire_hours * 3600}, request)


# ---------------- vben admin 前端兼容端点 ----------------
@router.get("/user/info")
def user_info(request: Request, user: User = Depends(current_user)):
    return ok({
        "userId": user.username,
        "username": user.username,
        "realName": user.display_name or user.username,
        "avatar": "",
        "roles": [user.role],
        "homePath": "/kb/qa",
        "desc": "某行核心系统迁移知识库",
    }, request)


@router.get("/auth/codes")
def auth_codes(request: Request, user: User = Depends(current_user)):
    return ok([f"role:{user.role}"], request)


@router.post("/auth/logout")
def logout(request: Request, user: User = Depends(current_user)):
    audit(request, user.username, "logout")
    return ok({}, request)


@router.post("/auth/refresh")
def refresh(request: Request, user: User = Depends(current_user)):
    return ok({"data": issue_token(user), "status": 0}, request)


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return ok({"username": user.username, "role": user.role, "display_name": user.display_name})
