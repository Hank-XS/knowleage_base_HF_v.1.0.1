"""统一响应包与错误码（设计文档 7.1/7.8）。"""
from typing import Any

from fastapi import Request


ERRORS = {
    "0": (200, "成功"),
    "40001": (400, "参数校验失败"),
    "40101": (401, "未认证或令牌失效"),
    "40301": (403, "无权限"),
    "40401": (404, "资源不存在"),
    "40901": (409, "状态冲突"),
    "42901": (429, "触发限流"),
    "50001": (500, "内部错误"),
    "50002": (504, "LLM 服务超时或不可用"),
    "50003": (500, "图谱查询失败"),
    "50004": (500, "向量库查询失败"),
    "50005": (422, "素材解析失败"),
}


class KbError(Exception):
    """code 必填；message/http 缺省时取错误码表默认值。"""

    def __init__(self, code: str, message: str | None = None, http: int | None = None):
        default_http, default_msg = ERRORS.get(code, (500, "内部错误"))
        self.code = code
        self.message = message or default_msg
        self.http = http or default_http
        super().__init__(self.message)


def _trace_id(request: Request | None) -> str:
    if request is None:
        return "-"
    return getattr(request.state, "trace_id", "-")


def ok(data: Any = None, request: Request | None = None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data, "trace_id": _trace_id(request)}


def err(code: str, message: str | None = None, request: Request | None = None) -> dict:
    default = ERRORS.get(code, (500, "内部错误"))[1]
    return {"code": int(code), "message": message or default, "data": None, "trace_id": _trace_id(request)}
