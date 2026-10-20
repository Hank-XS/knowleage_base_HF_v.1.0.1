# HSBC/CPS 主机系统测试数据集

围绕虚构跨境支付系统 **CPS (Cross-border Payment System)** 构造的四类资产测试数据，可用于文档解析、代码分析、依赖挖掘、知识图谱等场景验证。

## 目录结构

```
hf_data/
├── 01_tech_docs/           # 技术文档
│   ├── architecture/       # 架构设计书
│   ├── interfaces/         # MQ / REST 接口规范
│   ├── deployment/         # 部署手册
│   └── ops_logs/           # 运维日志 (JSONL)
├── 02_code_assets/         # 代码资产（已加厚）
│   ├── cobol/              # PYMAIN/PYROUTE/PYPOST/PYVAL + COPYBOOK
│   ├── rpg/                # RPGLE 多币种报表 + IFS CSV
│   ├── jcl/                # 多步骤 RECON/BACKUP + PROC
│   ├── rexx/               # DLQ 回放运维脚本
│   ├── mqsc/               # 队列/通道/触发器定义
│   ├── sql/                # 对账存储过程 + DDL
│   ├── shell/              # 部署冒烟脚本
│   ├── sched/              # Control-M EOD 依赖编排
│   ├── cics/               # CICS 交易/CSD
│   ├── data_dict/          # DB2 / VSAM 数据字典
│   └── github_cobol/       # GitHub 拉取：CardDemo/VAULT/zBANK 等（≥200行）
├── 03_business_rules/      # 业务规则
│   ├── requirements/       # 需求规格说明书
│   ├── process_flows/      # 流程图 + SWIFT 规则
│   └── tickets/            # 历史工单 / 缺陷
└── 04_system_metadata/     # 系统元数据
    ├── subsystem_call_matrix.csv
    ├── coupling_assessment.json
    └── module_dependency_frequency.csv
```

## 数据摘要

| 类别 | 文件数 | 说明 |
|------|--------|------|
| 技术文档 | 6 | 架构、MQ YAML、REST JSON、部署手册、2 天运维日志 |
| 代码资产 | 25+ | 真·屎山：GOTO 编排、三套手续费、重复 JCL、VIP 旁路、临时修复常驻、分脑 CICS、脚本失败也 exit 0 |
| 排雷笔记 | 1 | `02_code_assets/_LANDMINES.txt` |
| 业务规则 | 5 | SRS、Mermaid 流程、SWIFT 规则 YAML、工单清单+明细 |
| 系统元数据 | 3 | 调用矩阵、耦合度评估、依赖频次 |

## 关键实体（便于联调）

- 交易号示例：`CPS20241016000001`
- 核心程序：`PYMAIN` → `PYVAL` / `PYAML` / `PYROUTE` / `PYPOST` / `PYMSGOT`
- CICS 交易：`PYIN` `PYOT` `PYST` `PYFX`
- MQ 队列：`CPS.IN.Q` `CPS.OUT.Q` `AML.SCR.Q` `CPS.DLQ`
- 工单示例：`INC-88355`（死锁重复借记）、`INC-88421`（DLQ）

## 说明

全部为**合成测试数据**，不含真实客户信息或生产密钥；BIC/账号均为示意格式。
