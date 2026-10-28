# CodeGraph 分支：安装、启动与验收

本分支 `feat/codegraph-cobol-zip` 基于 `xxBank_konwleage_1026`，提供完整 COBOL 工程 ZIP 上传、后台解析、结构切片、代码关系图、源码定位和版本快照。无需 Docker 或大模型密钥即可使用这些功能。

## 1. 准备环境并拉取分支

需要 Git、Python 3.11+（本次实测 3.13）、Node.js **25.8.2** 和 pnpm **11.16.0**。前端原有配置要求 Node `^25.8.2`，不要按旧版 README 的 Node 20 安装。Windows x64 已完成实际验证；macOS/Linux 下方提供等价命令，尚未做平台实测。

```sh
git clone --branch feat/codegraph-cobol-zip --single-branch https://github.com/liangyefei/knowleage_base_HF_v.1.0.1.git
cd knowleage_base_HF_v.1.0.1
node --version
python --version
npm install -g pnpm@11.16.0
pnpm --version
```

已有仓库时，先保存自己的未提交工作，再执行 `git fetch origin` 和 `git switch --track origin/feat/codegraph-cobol-zip`；已存在本地同名分支则直接切换。以下安装命令都从仓库根目录开始。

## 2. 安装后端和解析器

Windows PowerShell：

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
npm ci --prefix backend/tools/codegraph --registry=https://registry.npmjs.org
```

macOS / Linux：

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
test -f backend/.env || cp backend/.env.example backend/.env
npm ci --prefix backend/tools/codegraph --registry=https://registry.npmjs.org
```

`npm ci` 会按锁文件安装 CodeGraph 1.6.2 及当前系统的平台包。不要使用 `--omit=optional`，平台包包含实际解析引擎。安装需要联网；代码解析本身不调用模型。Windows x64 默认使用平台包自带的 Node；其他环境使用 PATH 中的 Node。若需要指定解析用 Node，在启动后端的终端设置 `KB_CODEGRAPH_NODE` 为可执行文件的绝对路径。

首版保持 `.env` 中模型密钥、外部数据库连接为空。问答在此配置下使用模板答案与基础检索；代码结构解析照常工作。后续启用向量模型时需要统一重建索引，不能混用不同向量空间。

## 3. 启动后端

打开一个终端，进入仓库的 backend：

```powershell
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

macOS/Linux 将 `./.venv/Scripts/python.exe` 换为 `./.venv/bin/python`。保持单个 worker，不添加 `--workers`。首次启动会创建 SQLite 数据库和种子知识。

浏览器打开 `http://127.0.0.1:8000/api/v1/health` 检查后端，接口文档地址为 `http://127.0.0.1:8000/docs`。

## 4. 安装并启动前端

另开一个终端，从仓库根目录执行：

```sh
cd frontend
pnpm install --frozen-lockfile --registry=https://registry.npmjs.org
pnpm --filter @vben/web-antd exec vite --mode development --host 127.0.0.1 --port 5666 --strictPort
```

打开 `http://127.0.0.1:5666`，使用 `dev01 / dev123456` 或 `admin / admin123` 登录。前端 `/api` 自动代理到本机 8000 端口，使用现有 `.env.development`，无需复制其他机器的配置文件。上述命令是本地开发运行方式，不是公网生产部署配置。

## 5. 验收上传解析

从仓库根目录生成临时样例 ZIP：

```powershell
./backend/.venv/Scripts/python.exe backend/tests/code_project_sample.py backend/.local/cobol-demo.zip
```

macOS/Linux 同样替换 Python 路径。在「内容管理 → 上传资料 → 代码工程 ZIP」上传这个文件，填写工程名和版本，编码选择 UTF-8。

预期：3 个源码文件、12 个节点、13 条关系、4 个切片；一个 README 被跳过，`MISSING-SERVICE` 出现在未解析引用中。它是故意缺失的子程序，用于检查缺失依赖报告。切片可定位源码，图谱节点可点击查看源码；刷新后结果保留。「构建与治理 → 接入任务」可以重新打开任务和重试失败任务。

运行回归测试（PowerShell，单独的测试终端）：

```powershell
cd backend
$env:KB_DATA_DIR = "$PWD/.local/test-codegraph"
./.venv/Scripts/python.exe -m pytest tests/test_code_projects.py tests/test_runtime_stores.py tests/test_knowledge.py tests/test_source_view.py tests/test_kb.py -q
```

macOS/Linux：

```sh
cd backend
KB_DATA_DIR="$PWD/.local/test-codegraph" .venv/bin/python -m pytest tests/test_code_projects.py tests/test_runtime_stores.py tests/test_knowledge.py tests/test_source_view.py tests/test_kb.py -q
```

这 27 项测试已通过。另外在空白临时目录按 package-lock 执行 `npm ci` 并调用新安装的 CodeGraph 解析样例，确认得到预期的 12 个节点、13 条关系和 1 个未解析引用。测试结束关闭测试终端，避免把测试用 `KB_DATA_DIR` 带入日常服务。该变量由进程环境读取，不通过 `.env` 设置。前端构建已通过，但原有部分页面仍有 TypeScript 检查错误，详见功能说明。

## 6. 数据、限制和常见问题

- 本次不提交上传 ZIP、解析结果、截图、数据库、node_modules 或构建产物。测试源码通过脚本临时生成。
- 新环境没有其他机器已上传的工程，需自行上传。运行图谱与向量索引保存在 `backend/data/runtime/`，源码及快照保存在 `backend/data/objects/kb-raw/projects/`；都被 Git 忽略。SQLite 记录任务、文档和切片。迁移用户数据时，停止服务后整体备份 `backend/data`，不要只复制图谱文件。
- 从旧环境升级且要保留索引：停止后端，将原 `backend/data/graph_store.json` 和 `vector_store.json` 复制到 `backend/data/runtime/`（已存在运行索引时不要覆盖），再启动。仓库基线只作为首次读取的初始数据。
- ZIP 上限 50 MB，解压总量 200 MB，最多 5000 项、20 层目录，单个 UTF-8 源码上限 1 MB。支持 `.cbl/.cob/.cobol/.cpy`，编码 UTF-8 或 GB18030/GBK；EBCDIC 需先转换。
- 图谱包含静态结构与支持范围内的关系；动态调用、完整 SQL 表读写和 JCL 分析未覆盖。超过 100 行的结构单元会继续按行拆分。
- 解析器报模块缺失：重新在仓库根执行 CodeGraph 的 `npm ci`，确认没有省略 optional dependencies。
- 上传时报编码错误：选择与源码一致的编码；程序/Copybook 依赖缺失时，把相关文件一起打包并保留目录。
- 端口被占用：确认是否已运行本项目，避免重复启动。若修改后端端口，也需修改 `frontend/apps/web-antd/vite.config.ts` 中代理目标。
- 后端重启会将被中断的工程任务标为失败，可在任务页面重试。

完整能力、实现和测试记录见 [CodeGraph 工程接入首版](CodeGraph工程接入首版.md)。
