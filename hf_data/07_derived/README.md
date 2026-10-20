# 由现有 COBOL 反推的测试数据

源码在 `02_code_assets/github_cobol/`（CardDemo、VAULT-CBS、zBANK、LedgerCOBOL）。本目录是按那些 `PROGRAM-ID` / `CALL` / `XCTL` / 文件名补出来的文档和缺口程序，数字为测试估计。

| 目录 | 内容 |
|------|------|
| `01_tech_docs/` | 架构、MQ/API、部署、运维 JSONL |
| `02_code_fill/` | 缺失的 `CBSTM03B`、VAULT 短调用桩、JCL、CICS CSD、RPG、VSAM/文件字典 |
| `03_business_rules/` | SRS、电汇/ACH/日终流程图、工单 |
| `04_system_metadata/` | 调用矩阵、耦合度 |
