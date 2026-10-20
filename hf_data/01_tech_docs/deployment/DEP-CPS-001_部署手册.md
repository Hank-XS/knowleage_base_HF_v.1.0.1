# 部署手册：CPS 跨境支付系统

| 字段 | 值 |
|------|-----|
| 文档编号 | DEP-CPS-001 |
| 版本 | V1.6.0 |
| 适用环境 | DEV / SIT / UAT / PROD |
| 变更窗口 | 生产：周日 02:00–05:00 HKT |

## 1. 环境矩阵

| 环境 | LPAR | CICS Region | DB2 | MQ QMGR | 负载 |
|------|------|-------------|-----|---------|------|
| DEV | SYS1 | CPSD001 | DB2D | CPSQM.DEV | 单区 |
| SIT | SYS2 | CPSS001 | DB2S | CPSQM.SIT | 单区 |
| UAT | SYS3A/B | CPSU001/2 | DB2U | CPSQM.UAT | 双活 |
| PROD | SYS4A/B | CPSP001/2 | DB2P | CPSQM.PROD | GDPS 双活 |

## 2. 发布包清单

| 构件 | 数据集 / 路径 | 示例版本 |
|------|---------------|----------|
| COBOL Load Module | `CPS.PROD.LOAD` | PYMAIN V3.2.1 |
| CICS CSD | `CPS.PROD.CSD` | GROUP(CPSGRP) |
| DB2 DDL/DML | `CPS.PROD.DBRM` / Bind Package | PKG_PYPOST |
| JCL | `CPS.PROD.JCL` | PYRECON#, PYBACKUP# |
| MQ Object | MQSC `cps_queues.mqsc` | IF-MQ-CPS-001 V2.4 |

## 3. 部署步骤（PROD）

1. **冻结窗口**：关闭渠道入站开关 `CGW.CPS.ENABLE=N`
2. **备份**：执行 `PYBACKUP#`，确认 RC=0
3. **DB2 Bind**：`BIND PACKAGE(CPS) MEMBER(PYPOST) ISOLATION(CS)`
4. **CICS NEWCOPY**：`CEMT SET PROGRAM(PYMAIN) NEWCOPY`
5. **安装 CSD**：`CEDA INSTALL GROUP(CPSGRP)`
6. **MQ 变更**：`runmqsc CPSQM.PROD < cps_queues.mqsc`
7. **冒烟**：投递 3 笔 MT103 测试报文，校验状态至 SETTLED
8. **开放渠道**：`CGW.CPS.ENABLE=Y`
9. **观察**：监控 30 分钟，DLQ 深度=0，P99 < 800ms

## 4. 回退

| 场景 | 动作 |
|------|------|
| COBOL 异常 | NEWCOPY 回退至上一版本 Load |
| DB2 Bind 失败 | REBIND 上一 Package 版本 |
| MQ 定义错误 | 执行 `cps_queues_rollback.mqsc` |
| 严重故障 | GDPS 切换至备中心，RTO ≤ 15min |

## 5. 检查清单

- [ ] Change Ticket 已审批 (CHG-2024-10xxx)
- [ ] 依赖系统 AML / GLS 窗口对齐
- [ ] 值班人员就位（App + Infra + MQ）
- [ ] 回退包已上传并校验 checksum
