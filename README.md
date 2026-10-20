# 某行核心系统迁移知识库（Demo 实现）

依据《某行知识库项目详细设计文档 V1.0》实现的可运行原型：**离线构建＋在线问答**总体架构、单一 Flow 推理链、三级分流长时记忆、数据治理三步法闭环，以及迁移影响分析与代码骨架生成。

## 目录结构

```
kb-system/
├── backend/            FastAPI 后端（设计第 3-7 章的实现）
│   ├── app/            配置/存储层/离线管线/在线问答/路由
│   ├── data/seed/      ATM 场景种子素材（错误码表/mapping/报文/COBOL/文档）
│   ├── tests/          pytest 自测（指纹分流/入库/问答全链路/复核/影响分析）
│   ├── .env.example    配置模板（复制为 .env）
│   └── requirements.txt
├── frontend/           Vue3 + Vben Admin（Ant Design Vue 版）前端
└── docker-compose.yml  全套存储组件（可选，见下文）
```

## 快速启动（无 Docker / 无 LLM Key 也能跑）

双模式设计：未配置任何外部依赖时自动使用内嵌回退（SQLite / 文件图库 / 内嵌向量索引 / 本地对象目录）与 MockLLM（基于检索证据的模板作答），开箱即跑。

```bash
# 1) 后端（Python 3.11+）
cd backend
pip install -r requirements.txt
copy .env.example .env      # Windows；Linux/macOS 用 cp
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 首次启动自动建表并载入 ATM 种子知识（图谱+向量）

# 2) 前端（Node 20+，pnpm）
cd frontend
pnpm install
pnpm dev:antd               # http://localhost:5666
```

演示账号（登录页选择账号后自动带出密码）：

| 账号 | 密码 | 角色 | 权限 |
|---|---|---|---|
| dev01 | dev123456 | 研发 | 问答/检索/接入 |
| biz01 | biz123456 | 业务 | 问答/复核/治理 |
| gov01 | gov123456 | 治理员 | 全部（复核入库、治理校对） |
| admin | admin123 | 管理员 | 全部 |

## 启用真实大模型（OpenAI 兼容接口）

编辑 `backend/.env`：

```ini
KB_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 智谱 GLM 示例
KB_LLM_API_KEY=<你的 API Key>
KB_LLM_MODEL=glm-4.6
KB_EMB_MODEL=embedding-3                                # 向量模型
```

DeepSeek / Qwen / vLLM 本地服务均可（任何 OpenAI 兼容 `/chat/completions` 与 `/embeddings`）。重启后端即切换：问答综合、AI 打标走真实模型，Embedding 走真实向量；前端「系统状态」页可查看当前模式。

## 已实现能力（对应设计文档章节）

- **离线构建（第 3 章）**：五类素材接入适配器（错误码表/mapping/报文/文档/COBOL），parse→clean→tag→review→merge→index 六步流水线；`hf_data` 数据集清洗（L0—L4、隔离/冲突台账、tier/trust 分层）产出可导入图谱与向量；COBOL 段级解析，AI/规则打标＋治理工作台人工校对，知识版本与已验证答案失效联动
- **知识存储（第 4 章）**：图谱 15 类节点/13 类关系（业务/数据/执行三层），向量三集合，指纹/答案/任务/审计等关系表，对象存储路径规范
- **在线问答（第 5 章）**：单一 Flow（问题分析→指纹→三级分流→多路检索→重排→LLM 综合→带依据作答），精确直出/参考复用/实时推理，追问增量上下文，复核沉淀闭环，答案三段式（是什么/为什么/怎么处理）＋逐条溯源＋推理轨迹
- **工具接口层（第 6 章）**：统一注册中心，search_graph/search_doc/search_code/query_cache/save_answer 五个规范化工具，为 Agent 动态编排预留
- **REST 接口（第 7 章）**：问答/检索/溯源/治理/接入/影响分析/代码生成/版本/工具，统一响应包与错误码，JWT＋RBAC 五角色，trace_id 与审计
- **前端**：Vben Admin 定制的问答控制台、治理工作台、知识接入、影响分析与代码生成、系统状态五个页面

## 切换到真实存储组件（可选，需 Docker）

```bash
docker compose up -d        # PostgreSQL + Neo4j + Milvus + MinIO
```

在 `backend/.env` 中取消以下注释并重启后端：

```ini
KB_PG_DSN=postgresql+psycopg://kb:kb@localhost:5432/kb
KB_GRAPH_URL=bolt://localhost:7687
KB_GRAPH_PASSWORD=kbpass
KB_VECTOR_URI=http://localhost:19530
KB_S3_ENDPOINT=localhost:9000
KB_S3_ACCESS_KEY=kbminioadmin
KB_S3_SECRET_KEY=kbminioadmin
```

另需安装对应驱动：`pip install psycopg2-binary neo4j pymilvus minio`。

## MCP Tools（Agent 自动调度）

知识库能力已拆成可调度工具（`search_doc` / `search_code` / `search_graph` / `query_cache` 等），供：

1. **MCP Server**：Cursor / Claude Desktop 等 Host 的模型自动选工具；
2. **HTTP Agent**：`POST /api/v1/qa/ask_agent`（前端问答页开关「Agent 自动调度工具」）；
3. **单一 Flow**：原固定流水线仍可用。

```bash
cd backend
pip install -r requirements.txt
python -m app.mcp_server          # stdio MCP
```

Cursor 配置示例见 [`mcp/hf-kb.mcp.json`](mcp/hf-kb.mcp.json)，把其中 `cwd` 改成你的本机 `backend` 路径后，合并进 Cursor MCP 设置。

工具清单：`GET /api/v1/qa/tools`。

知识接入工具链（建库/图谱）：

```bash
cd backend
python scripts/mcp_ingest_once.py          # scan→clean→build_graph→stats
```

## 自测

```bash
cd backend && python -m pytest tests/ -q
```

## 边界声明（会议决议）

- 系统对 AI 解析出的业务逻辑准确性不承担责任，最终以人工复核为准（miss 答案必须复核后方可沉淀入库）
- 不涉及将生成代码在大机上运行测试，代码生成仅输出骨架与人工校验点
