# 安装与启动

项目提供文档知识库、COBOL 工程分析、结构切片、图谱、版本对比、引用映射和问答。无需 Docker 或模型密钥即可运行，全新安装首次启动为空知识库。

## 环境与源码

需要 Git、Python 3.11+、Node.js 25.8.2、pnpm 11.16.0。下方分别提供 Windows 和 macOS/Linux 命令。

```sh
git clone <仓库地址> knowledge-base
cd knowledge-base
npm install -g pnpm@11.16.0
```

如果使用纯源码包，解压后进入 `knowledge-base` 目录。以下命令都从仓库根目录开始。

## 后端与解析器

Windows PowerShell：

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
npm ci --prefix backend/tools/codegraph --registry=https://registry.npmjs.org
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

macOS/Linux：

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
test -f backend/.env || cp backend/.env.example backend/.env
npm ci --prefix backend/tools/codegraph --registry=https://registry.npmjs.org
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

保持单个后端 worker。CodeGraph 按独立 lockfile 安装，不要省略 optional dependencies；它们包含平台解析引擎。Windows x64 默认使用依赖附带的 Node；需要指定运行时可设置 `KB_CODEGRAPH_NODE` 为可执行文件绝对路径。

首次启动只建表并初始化登录账号、词表和提示词。默认 `KB_AUTO_IMPORT=false`，不导入业务素材。后端健康检查为 `http://127.0.0.1:8000/api/v1/health`，接口文档为 `http://127.0.0.1:8000/docs`。

## 前端

另开终端，从仓库根目录执行：

```sh
cd frontend
pnpm install --frozen-lockfile --registry=https://registry.npmjs.org
pnpm --filter @vben/web-antd exec vite --mode development --host 127.0.0.1 --port 5666 --strictPort
```

访问 `http://127.0.0.1:5666`，演示账号为 `dev01 / dev123456` 或 `admin / admin123`。开发环境 `/api` 代理到本地后端。模型、外部存储和账号权限配置见根目录 README；服务密钥只写目标机器的 `backend/.env`。

## 生产构建

```sh
cd frontend
pnpm build:antd
```

产物在 `frontend/apps/web-antd/dist`。生产配置使用 `/api`，部署时将 `/api/*` 转发到后端 `/api/v1/*`，避免重复拼接 `v1`。源码仓库不包含构建产物、依赖目录和实际服务配置。

## 模型与 Demo 配置

后端从 `backend/.env` 加载配置，进程环境变量优先。生成模型的接口、密钥与模型名配置见根目录 [README](../README.md)，完整字段见 [配置模板](../backend/.env.example)。

```ini
KB_QA_STRATEGY=auto
KB_RERANK_ENABLED=false
KB_LLM_THINKING=disabled
KB_MODEL_DEVICE=cpu
KB_MODEL_CPU_THREADS=4
```

聊天框使用单一输入。`auto` 让普通事实与定位问题走固定检索后生成，复杂比较、影响或调用链问题使用 Agent。前端发送 `mode=auto`；显式 `mode=agent` 或 `mode=flow` 优先于自动策略。

Demo 默认关闭模型重排，保留原文匹配、BM25 与语义向量融合，不加载重排模型。前后端更新后应重新构建前端并重启后端。只切换重排开关无需重建向量索引。

### 本地语义向量

使用本地模型时，在后端虚拟环境安装额外依赖：

```sh
python -m pip install -r requirements-retrieval.txt
```

将完整的模型目录放到部署机器，并在 `.env` 配置该机器上的绝对路径。例如：

```ini
KB_EMB_LOCAL_PATH=/opt/kb/models/Qwen3-Embedding-0.6B
KB_EMB_MODEL=Qwen3-Embedding-0.6B
```

Windows 路径可使用 `D:/models/Qwen3-Embedding-0.6B`。离线部署需一并准备模型配置、tokenizer、权重及 revision 文件；问答请求不会自动下载模型。联网准备机器可执行 `python scripts/download_retrieval_models.py` 下载 Embedding 与可选重排模型。

本地路径配置后优先使用本地模型。使用远端向量服务时清空 `KB_EMB_LOCAL_PATH`，并配置 `KB_EMB_BASE_URL`、`KB_EMB_API_KEY`、`KB_EMB_MODEL`；不要把只有聊天接口的服务作为向量服务。

### 索引构建、激活与回滚

以下命令在 `backend` 目录执行，`python` 使用已安装依赖的后端虚拟环境。已有非语义索引或更换 Embedding 模型、维度、指令模板后，需要重建；日常上传使用当前配置生成索引。

```sh
# 离线构建暂存代，不覆盖当前索引
python scripts/rebuild_retrieval.py --stage-only

# 停止后端写入后，使用构建结果中的 generation_id 激活，再重启后端
python scripts/rebuild_retrieval.py --activate <generation_id>

# 需要恢复时，停止后端后回滚到该次构建前的索引
python scripts/rebuild_retrieval.py --rollback <generation_id>
```

暂存代、原文摘要与回滚文件保存在 `backend/data/runtime/index-generations/`。原文、切片或权限已变化时，旧代激活与回滚会被拒绝，应重新构建，避免恢复已清理或已撤权内容。本地内嵌存储保持单进程，不支持多个后端进程同时写入。

### 可选模型重排

仅在需要对比排序质量时启用，并配置本地重排模型路径或远端服务：

```ini
KB_RERANK_ENABLED=true
KB_RERANK_LOCAL_PATH=/opt/kb/models/Qwen3-Reranker-0.6B
KB_RERANK_CANDIDATES=12
KB_RERANK_MAX_TOKENS=1024
KB_RERANK_BATCH_SIZE=4
KB_RERANK_CACHE_SIZE=2048
```

远端服务使用 `KB_RERANK_URL` 并清空本地重排路径。关闭开关时，即使保留路径也不会加载模型。输入预算会影响候选排序；耗时与相关性应使用实际业务问题评估。

## 使用与检查

上传自己的 DOCX、文本型 PDF、Markdown 或完整 COBOL 工程 ZIP，按系统、工程、版本和主题标签归档。具体操作和问答行为见 [知识库分类与文档接入](知识库分类与文档接入.md)。

回归测试会在临时目录生成合成素材：

```sh
cd backend
python -m pytest tests -q
```

业务运行数据保存在 `backend/data/`，均被 Git 忽略。新机器没有已上传的资料，需自行接入；迁移数据时停止服务后整体备份数据目录。不要将原文、切片、图谱、数据库、索引、日志或截图提交到 GitHub。

端口占用时先检查已有服务；修改后端端口时同步修改前端代理。解析器模块缺失时重新执行 CodeGraph 的 `npm ci`。源码上传和打包规则见 [GitHub源码上传说明](GitHub源码上传说明.md)。
