# 需求规格说明书：SWIFT 报文处理

| 字段 | 值 |
|------|-----|
| 文档编号 | SRS-CPS-SWIFT-001 |
| 版本 | V2.1.0 |
| 关联系统 | CPS |
| 状态 | Approved |

## 1. 业务目标

支持客户发起的跨境汇出（Customer Credit Transfer）及同业汇划（FI Transfer），覆盖 MT103 / MT202 及 ISO20022 pacs.008 / pacs.009。

## 2. 功能需求

| ID | 需求描述 | 优先级 | 验收标准 |
|----|----------|--------|----------|
| FR-001 | 系统应解析 MT103 字段 20/32A/50/59/70 | Must | 解析成功率 ≥ 99.9% |
| FR-002 | 金额 > 0 且币种在白名单内方可受理 | Must | 非法币种返回 VAL002 |
| FR-003 | 所有汇出须调用 AML 筛查 | Must | 无 AML 结果不得过账 |
| FR-004 | AML 超时 5s 交易置 HOLD_AML | Must | 超时后可人工/自动续跑 |
| FR-005 | USD/EUR/GBP 默认走 SWIFT 通道 | Must | 路由日志可追溯 |
| FR-006 | CNY 走 CNAPS，失败可降级 SWIFT | Should | 降级需记录 ROUTE_FB |
| FR-007 | HKD 小额（≤10,000）可走 LOCAL | Could | 阈值可配置 |
| FR-008 | 提供 REST 查询支付状态 | Must | 与 DB2 状态一致 |
| FR-009 | 支持幂等提交（Idempotency-Key） | Must | 24h 内重复键不重复记账 |
| FR-010 | 日终 Nostro 对账差异生成工单 | Must | 差异金额写入 BREAK 文件 |

## 3. 业务规则摘要

### BR-AMT-01 金额校验
- 金额必须 > 0
- 小数位遵循币种规则（JPY=0, USD=2, KWD=3）

### BR-AML-01 制裁筛查
- 付款人、收款人、银行 BIC 均需筛查
- 命中 HIT → 状态 REJECTED，原因 AML001
- 可疑 SUSPECT → HOLD_AML，转人工复核

### BR-RTE-01 路由优先级
1. 强制路由表（按收款行 BIC）
2. 币种默认通道
3. Nostro 余额充足性检查
4. 通道可用性（MQ 深度 / 对方系统心跳）

### BR-STL-01 起息日
- 同日清算截止：15:00 HKT（SWIFT）、16:30（CNAPS）
- 超过截止自动滚动至下一营业日

## 4. 非功能需求

| ID | 描述 | 指标 |
|----|------|------|
| NFR-001 | 联机吞吐 | 峰值 850 TPS |
| NFR-002 | 可用性 | 99.95% |
| NFR-003 | 审计 | 全量报文保留 7 年 |
