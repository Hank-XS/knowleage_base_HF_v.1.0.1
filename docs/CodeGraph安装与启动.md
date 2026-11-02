# 安装与启动

本分支提供文档知识库、COBOL 工程分析、结构切片、图谱、版本对比、引用映射和问答。无需 Docker 或模型密钥即可运行，首次启动为空知识库。

## 环境与源码

需要 Git、Python 3.11+、Node.js 25.8.2、pnpm 11.16.0。Windows x64 已验证；下方提供 macOS/Linux 对应命令。

```sh
git clone --branch feat/knowledge-platform-source-20261102 --single-branch https://github.com/Hank-XS/knowleage_base_HF_v.1.0.1.git
cd knowleage_base_HF_v.1.0.1
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

## 使用与检查

上传自己的 DOCX、文本型 PDF、Markdown 或完整 COBOL 工程 ZIP，按系统、工程、版本和主题标签归档。具体操作见 [知识库分类与文档接入](知识库分类与文档接入.md)，检索行为见 [通用检索方案](通用检索方案.md)。

回归测试会在临时目录生成合成素材：

```sh
cd backend
python -m pytest tests -q
```

业务运行数据保存在 `backend/data/`，均被 Git 忽略。新机器没有已上传的资料，需自行接入；迁移数据时停止服务后整体备份数据目录。不要将原文、切片、图谱、数据库、索引、日志或截图提交到 GitHub。

端口占用时先检查已有服务；修改后端端口时同步修改前端代理。解析器模块缺失时重新执行 CodeGraph 的 `npm ci`。源码上传和打包规则见 [GitHub源码上传说明](GitHub源码上传说明.md)。
