# GitHub 源码上传说明

## 上传范围

保留后端和前端功能源码、CodeGraph 接入脚本与依赖锁文件、配置模板、Markdown/HTML 说明和自动化测试代码。测试代码在运行时创建合成素材，不附带上传文件或知识库数据。

以下内容只留在本地，不上传：

- `backend/data/`、`hf_data/` 的实际内容，分别只保留目录说明 `README.md`。
- 上传的代码 ZIP 和原文件、Word/PDF/Markdown 资料，以及由它们生成的数据库、历史问答、切片、图谱、向量索引和 CodeGraph 索引。
- `backend/.local/` 等本地验收脚本输出、截图、结果 JSON、日志及测试报告，`backend/tests/fixtures/` 的落地样本。
- 本机业务评测问题集（包括 `backend/scripts/qa_cases.json`）；评测工具要求使用者显式提供 `--cases`，源码不携带固定业务题。
- 本地模型权重（如 `.safetensors`、`.pt`、`.pth`、`.ckpt`、`.onnx`），需在部署机器单独准备。
- Python / Node 依赖、构建后的 `dist` 和压缩包、缓存和进程记录。
- 本机 `.env`、私钥和实际服务密钥；原始 Word 项目资料。维护后的说明放在 `docs/`。

前端 `.env.development`、`.env.production`、`.env.analyze` 是公开构建参数，允许提交。不要往 `VITE_*` 参数写服务端密钥。当前 web-antd 的开发与生产 API 地址均为 `/api`；正式部署时将它转发到后端 `/api/v1`。后端配置从 `.env.example` 复制并在目标机器填写，默认 `KB_AUTO_IMPORT=false`。

## 审查并生成纯源码包

从仓库根目录执行（Windows 使用已创建的 Python 环境）：

```powershell
# 审查当前工作区，不修改 Git 或运行数据。
./backend/.venv/Scripts/python.exe backend/scripts/prepare_source.py

# 输出到仓库外；包含当前未提交的源码改动。
./backend/.venv/Scripts/python.exe backend/scripts/prepare_source.py --output ../release/knowledge-base-source.zip --report ../release/source-audit.json
```

macOS/Linux 将 Python 命令换成 `backend/.venv/bin/python`。脚本按路径策略二次排除已跟踪的数据和产物，检查常见密钥格式，遇到疑似实际密钥时只报告位置并停止，不回显密钥。ZIP 创建后校验 CRC 和文件范围。报告仅包含路径、大小、摘要及检查结果，不包含资料正文。此检查覆盖常见泄漏格式，不代替对业务内容的人工审查。

源码包不包含 `.git`。新仓库可以解压后初始化 Git，避免带入旧仓库历史；不要把本地整个父目录、依赖环境或测试 ZIP 一起上传。正常安装步骤见 [安装与启动](CodeGraph安装与启动.md)。启动新安装会创建空知识库。

当前目标仓库为 `https://github.com/Hank-XS/knowleage_base_HF_v.1.0.1.git`，目标分支为 `feat/knowledge-platform-source-20261102`。ZIP 内的 `knowledge-base/` 是项目根目录，上传到现有仓库时使用该目录内的文件，避免额外嵌套一层目录；不要直接将 ZIP 作为源码文件提交。

## 在当前仓库提交

`.gitignore` 不会自动取消已跟踪文件。因此旧样例数据和原始 Word 资料需要从 Git 索引移除，本地资料可保留。此整理不改写历史提交；已存在的历史内容不会因忽略规则而消失。

```sh
git status --short
git add -A
git diff --cached --stat
git diff --cached --name-only
```

确认暂存区只包含源码和说明更新，以及旧资料的删除记录，再自行提交和推送到目标仓库。源码导出脚本不执行提交、推送或历史重写。
