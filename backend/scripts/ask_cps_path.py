import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def call(method, path, token=None, body=None, timeout=180):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def main() -> None:
    login = call(
        "POST",
        "/api/v1/auth/login",
        body={"username": "gov01", "password": "gov123456"},
    )
    token = login["data"]["accessToken"]
    sess = call("POST", "/api/v1/qa/sessions", token, {})
    sid = sess["data"]["session_id"]
    q = "CPS 一笔跨境汇出的关键路径是怎样的？"
    ans = call("POST", "/api/v1/qa/ask", token, {"session_id": sid, "question": q})
    d = ans["data"]
    a = d.get("answer") or {}
    print("uncovered=", a.get("uncovered"), "confidence=", a.get("confidence"))
    print("WHAT:", a.get("what"))
    print("HOW:", a.get("how"))
    print("SOURCES:")
    for s in (d.get("sources") or [])[:8]:
        print(f"  [{s.get('no')}] {s.get('path') or s.get('label')} score={s.get('score')}")


if __name__ == "__main__":
    main()
