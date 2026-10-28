# CodeGraph 工程接入首版

其他机器首次安装请阅读 [安装、启动与验收说明](CodeGraph安装与启动.md)。

## 使用

1. 进入「内容管理 → 上传资料 → 代码工程 ZIP」。
2. 选择知识库，填写工程名称、版本和源码编码，上传保留目录结构的 ZIP。
3. 上传后自动进入任务详情。后台执行工程解压、结构解析、生成切片、结果入库。
4. 完成后查看「解析报告 / 工程源码 / 结构切片 / 代码关系图」。切片的「定位源码」和图谱节点均可跳转并高亮对应行。
5. 「构建与治理 → 接入任务」可查看工程历史；失败任务可重试。原有结构化资料接入功能保留。

ZIP 应同时包含主程序、被调用程序和 Copybook。首版解析 `.cbl / .cob / .cobol / .cpy`，其他文件列入跳过报告，保留在原始 ZIP 中，不执行工程内任何脚本。

限制：ZIP 50 MB、解压总量 200 MB、5000 个条目、20 层目录、单个源码文件转换为 UTF-8 后 1 MB。支持 UTF-8（含 BOM）、GB18030 / GBK。EBCDIC 请先转换编码。

## 版本与结果

- 工程身份为「知识库 + 工程名称」，每次上传生成独立快照。
- 同一工程的不同版本独立保存，任务详情仅展示当前快照的图谱。
- 同一版本重新上传：解析成功后移除该版本旧快照的图谱和检索条目，旧文档标记 archived；历史任务仍能查看原始源码和结果。
- 解析失败不会替换原有成功结果。重试创建新任务，保留原失败记录。
- 全局知识库可包含多个版本；查看具体版本的关系请进入对应工程任务。首版未增加问答页面的工程版本筛选。
- 源码和结构切片同时登记到现有文档、版本和切片表；切片保留源码路径、起止行号和字符偏移。

## 实现与安装

CodeGraph 固定为 `@colbymchenry/codegraph@1.6.2`，有独立 lockfile。在仓库根目录执行：

```powershell
npm ci --prefix backend/tools/codegraph --registry=https://registry.npmjs.org
```

后端通过 `backend/tools/codegraph/index-project.cjs` 调用真实 SDK，在每个快照目录生成 SQLite 索引，然后转换到现有图谱和切片结构。Windows x64 优先使用依赖自带的 Node 运行时；其他环境需 Node 22.5+，也可通过 `KB_CODEGRAPH_NODE` 指定 Node 可执行文件。

没有安装 AI 编辑器插件，没有调用大语言模型。CodeGraph 遥测通过 `CODEGRAPH_TELEMETRY=0` 和 `DO_NOT_TRACK=1` 关闭。首版检索使用项目现有 HashEmbedder 的 256 维本地基础索引；若后续启用真正的向量模型，需要统一重建索引，不能混用不同向量空间。

新增接口均在 `/api/v1/code-projects`：上传、任务列表、任务详情、失败重试，以及任务下的 `source / chunks / graph`。读接口需要登录，上传和重试需要 dev / gov / admin 角色，沿用现有应用共享知识库的访问模式。

后台是单进程中的串行任务线程，适用于当前本地部署。启动保持一个 uvicorn worker。重启中断的任务标记失败，用户可重试；不宣称支持分布式队列或断点续跑。

## 能力边界

提取代码结构、静态调用 / 跳转、COPY 依赖、数据项及支持范围内的引用，不自动生成完整业务语义图谱。动态调用、JCL 和完整 SQL 表读写分析不属于本次交付。缺失依赖显示为未解析引用，文件未被识别或发生解析异常也会显示在报告中。

结构切片来自段落与数据定义；超过 100 行的单元按行继续拆分并保留相同结构标识。未识别到可切片结构的文件使用明确标注的文件切片。图谱单次展示最多 500 个节点和 1500 条关系，超限会提示按文件筛选。

## 验证记录（2026-10-28）

- 新增后端测试 13 项通过：真实解析器、跨文件 CALL / COPY、缺失依赖、切片与源码行对应、实际图谱与检索入库、同版本替换、不同版本隔离、失败保留与重试、入库失败恢复旧快照、ZIP 路径与编码校验、权限校验。
- 原有文档管理、源码预览和知识库测试 12 项通过。
- 浏览器实际操作：登录、上传完整 ZIP、轮询完成、查看报告与缺失依赖、切片定位源码、关系图渲染、刷新后读取结果、任务列表、原文档上传均通过。修复了共用请求客户端将 FormData 按 JSON 发送的问题。
- 样例包含主程序、被调用程序、Copybook 和一个跳过的文本文件：3 个源码文件、12 个节点、13 条关系、4 个切片，故意缺失的 `MISSING-SERVICE` 被报告。
- 前端生产构建通过。全量 TypeScript 检查仍存在原治理、问答、总览等页面的既有类型错误；本次新增页面没有类型错误。

可复现后端测试（使用独立数据目录，避免修改本地演示数据）：

```powershell
cd backend
$env:KB_DATA_DIR = "$PWD/.local/test-codegraph"
./.venv/Scripts/python.exe -m pytest tests/test_code_projects.py -q
./.venv/Scripts/python.exe -m pytest tests/test_knowledge.py tests/test_source_view.py tests/test_kb.py -q
```

测试在运行时通过 `backend/tests/code_project_sample.py` 生成最小合成源码，不提交上传数据或生成的 ZIP。浏览器脚本为 `backend/tests/browser-code-project.cjs`，依赖已安装的前端 Playwright 和本机 Edge（可用 `BROWSER_PATH` 覆盖），自动把样例 ZIP、截图及结果写入被忽略的 `backend/.local/browser-code-project/`。

## 提交范围与运行数据

提交功能源码、CodeGraph 桥接脚本及 package-lock、自动化测试代码和本说明。依赖目录、数据库、上传工程、解析快照、日志、截图、ZIP 和构建产物均不提交。

图谱和向量索引的运行结果写入 `backend/data/runtime/graph_store.json` 与 `backend/data/runtime/vector_store.json`，该目录已被 Git 忽略。运行索引不存在时，读取仓库原有的 `backend/data/graph_store.json` 和 `vector_store.json` 作为初始数据；后续保存只写运行目录，不修改仓库基线。旧环境升级时可先将现有两份索引复制到运行目录，再恢复仓库基线。

原仓库已经跟踪的种子数据和历史样例保留原样，本次不新增验收数据。可用 `git status --short` 核对待提交文件；提交前确保没有 `.env`、上传文件和运行索引混入。`tests/test_runtime_stores.py` 验证了基线只读、运行结果持久化及重新加载行为。

整理后复验：工程解析 13 项、运行存储 2 项、现有文档/来源预览/知识库 12 项，共 27 项通过；`git diff --check` 通过，`backend/data` 下已跟踪文件无差异。
