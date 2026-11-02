# 知识库与代码工程分析平台

管理 DOCX、文本型 PDF、Markdown 文档与 COBOL 代码工程，提供结构切片、代码关系图、版本对比、代码文档映射和可溯源问答。后端使用 FastAPI，前端使用 Vue3 / Vben Admin。代码工程通过 CodeGraph 解析；无大模型密钥时也可运行，并使用关键词检索展示原文依据。

## 目录结构

```
kb-system/
├── backend/            FastAPI 后端（设计第 3-7 章的实现）
│   ├── app/            配置/存储层/离线管线/在线问答/路由
│   ├── data/           本地运行数据（默认空库，不附带业务素材）
│   ├── tests/          pytest 自测（指纹分流/入库/问答全链路/复核/影响分析）
│   ├── .env.example    配置模板（复制为 .env）
│   └── requirements.txt
├── frontend/           Vue3 + Vben Admin（Ant Design Vue 版）前端
└── docker-compose.yml  全套存储组件（可选，见下文）
```

## 快速启动（无 Docker / 无 LLM Key 也能跑）

请优先按 [安装与启动说明](docs/CodeGraph安装与启动.md) 操作，包含 Windows / macOS / Linux 命令、CodeGraph 依赖安装、生产构建及运行数据说明。

双模式设计：未配置任何外部依赖时自动使用内嵌回退（SQLite / 文件图库 / 内嵌向量索引 / 本地对象目录）与 MockLLM（基于检索证据的模板作答），开箱即跑。

工程只保留功能和必要配置，不附带源码资产、文档、切片、图谱或历史问答。默认 `KB_AUTO_IMPORT=false`，重启和页面查询不会恢复演示数据；登录后上传文档或代码工程 ZIP 即可接入自己的资料。数据集同步与接入工具仍可显式调用。测试会在临时目录生成合成素材，不依赖仓库数据。

资料统一按「系统 → 工程 → 文件」归档，配合用途、版本和主题标签筛选。文档仅支持 DOCX、文本型 PDF、Markdown，并按正文结构切割。操作及升级说明见 [知识库分类与文档接入](docs/知识库分类与文档接入.md)。

## 源码上传与分发

仓库只包含功能源码、配置模板、锁文件、说明和回归测试代码。上传样本、数据库、历史问答、切片、图谱、向量索引、截图、日志、依赖目录、构建产物和本机 `.env` 不应提交。运行测试时生成的合成素材保存在临时目录，不随源码分发。

上传准备及纯源码打包命令见 [GitHub 源码上传说明](docs/GitHub源码上传说明.md)。脚本使用当前工作区的最新源码，包含尚未提交的新功能；不会把本地运行数据或 `.git` 历史打入源码包。

```bash
# 1) 后端（Python 3.11+）
cd backend
pip install -r requirements.txt
copy .env.example .env      # Windows；Linux/macOS 用 cp
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 首次启动自动建表并初始化登录账号、词表和提示词，知识库为空

# 2) 前端（Node 25.8.2，pnpm 11.16.0；另开终端，从仓库根目录开始）
cd frontend
pnpm install --frozen-lockfile
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
KB_EMB_BASE_URL=<兼容 embeddings 接口的服务地址>
KB_EMB_API_KEY=<向量服务密钥>
KB_EMB_MODEL=embedding-3                                # 向量模型
```

生成服务使用兼容 `/chat/completions` 的接口，向量服务使用兼容 `/embeddings` 的接口，二者可分别配置。仅填写生成模型密钥不会自动启用语义向量检索；需显式配置 `KB_EMB_BASE_URL`。未配置向量服务时使用 BM25 和精确标识符检索。旧哈希索引不会混作新语义索引，需重新导入或重建对应向量。前端「系统状态」可查看模型模式，检索流程见 [通用检索方案](docs/通用检索方案.md)。

## 已实现能力（对应设计文档章节）

- **离线构建（第 3 章）**：五类素材接入适配器（错误码表/mapping/报文/文档/COBOL），parse→clean→tag→review→merge→index 六步流水线；`hf_data` 数据集清洗（L0—L4、隔离/冲突台账、tier/trust 分层）产出可导入图谱与向量；COBOL 段级解析，AI/规则打标＋治理工作台人工校对，知识版本与已验证答案失效联动
- **知识存储（第 4 章）**：图谱 15 类节点/13 类关系（业务/数据/执行三层），向量三集合，指纹/答案/任务/审计等关系表，对象存储路径规范
- **在线问答（第 5 章）**：精确标识符、BM25、原文上下文和图谱检索，可选语义召回与重排；默认展示简明答案，补充说明和依据按需查看；支持按账号保存历史会话及继续追问、复核答案复用与工程版本校验。工具执行记录保存在后台。
- **工具接口层（第 6 章）**：统一注册中心，search_graph/search_doc/search_code/query_cache/save_answer 五个规范化工具，为 Agent 动态编排预留
- **REST 接口（第 7 章）**：问答/检索/溯源/治理/接入/影响分析/代码生成/版本/工具，统一响应包与错误码，JWT＋RBAC 五角色，trace_id 与审计
- **前端**：知识库列表、上传资料、切片查看、版本对比、代码文档映射、图谱、问答、代码树与影响分析等页面。治理与接入任务的实现保留，当前导航不展示。

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
