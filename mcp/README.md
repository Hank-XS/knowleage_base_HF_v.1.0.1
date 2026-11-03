# 某行知识库 MCP 接入

将 `search_doc` / `search_code` / `search_graph` 等能力暴露为 MCP Tools，由 Cursor 等 Host **自动调度**。

## 1. 安装

```bash
cd backend
pip install -r requirements.txt
# 要求 mcp>=1.9,<2（与当前 FastAPI 的 starlette 兼容）
```

## 2. 本地自检

```bash
cd backend
python -c "from app.mcp_server import build_mcp; build_mcp(); print('ok')"
python -m app.mcp_server   # stdio，供 MCP Host 拉起
```

## 3. Cursor 配置

把 [`hf-kb.mcp.json`](./hf-kb.mcp.json) 中的内容合并到 Cursor 的 MCP 设置（注意改 `cwd` 为本机路径）：

```json
{
  "mcpServers": {
    "hf-kb": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/absolute/path/to/knowledge-base/backend",
      "env": {
        "KB_AUTO_IMPORT": "false"
      }
    }
  }
}
```

配置后在对话里可直接问业务问题，模型会自动调用例如：

- `analyze_question` → `query_cache`
- `search_graph` / `search_doc` / `search_code`
- `impact_analyze` / `preview_source`

## 4. 知识接入 / 图谱构建工具链

| 工具 | 作用 |
|------|------|
| `scan_dataset` | 盘点 hf_data |
| `clean_dataset` | 清洗 → `08_cleaned` |
| `build_knowledge_graph` | 三元组入图谱 + chunk 入向量 |
| `upload_knowledge` | 单文件 base64 上传并六步接入 |
| `ingest_knowledge_base` | 一键：scan→clean→build→stats |

本地按链路跑一次：

```bash
cd backend
python scripts/mcp_ingest_once.py
# 或一键：
python scripts/mcp_ingest_once.py --one-shot
```

## 5. 与 Web 问答的关系

| 入口 | 编排方式 |
|------|----------|
| MCP Host（Cursor） | Host 侧模型自动选 MCP Tools |
| `POST /qa/ask_agent` | `mode=auto` 按复杂度选择 Flow/Agent；可显式指定 `agent` 或 `flow` |
| `POST /qa/ask` | 原单一 Flow 固定流水线 |

前端问答页保留单一输入框，后台自动匹配，无模式开关。Demo 默认关闭模型重排，生成模型与语义向量可分别配置，见 [安装与启动](../docs/CodeGraph安装与启动.md)。
