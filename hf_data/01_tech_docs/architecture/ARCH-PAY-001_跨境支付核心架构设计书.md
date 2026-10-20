# 架构设计书：跨境支付核心系统 (CPS)

| 字段 | 值 |
|------|-----|
| 文档编号 | ARCH-PAY-001 |
| 版本 | V3.2.1 |
| 系统代号 | CPS (Cross-border Payment System) |
| 平台 | IBM z/OS 2.5 / CICS TS 6.1 / DB2 12 |
| 编制日期 | 2024-11-15 |
| 密级 | 内部 |

## 1. 系统定位

CPS 负责 SWIFT MT/MX 报文收发、清算路由、账务记账与对账，对接下行渠道网关 (CGW)、核心账务 (GLS)、反洗钱筛查 (AML)。

## 2. 逻辑分层

```
┌─────────────────────────────────────────────────────┐
│ 渠道层  CGW / API Gateway / MQ Listener             │
├─────────────────────────────────────────────────────┤
│ 交易层  CICS: PYIN / PYOT / PYST / PYFX             │
├─────────────────────────────────────────────────────┤
│ 业务层  COBOL: PYMAIN / PYROUTE / PYVAL / PYPOST    │
├─────────────────────────────────────────────────────┤
│ 数据层  DB2: PYDB / VSAM: PYVSAM.ACCT / PYVSAM.CTRL │
└─────────────────────────────────────────────────────┘
```

## 3. 子系统一览

| 子系统 | 代号 | 职责 | 主程序 |
|--------|------|------|--------|
| 报文接入 | MSGIN | MT103/MT202/pacs.008 解析入库 | PYMSGIN |
| 路由引擎 | ROUTE | 清算行选择、通道优选 | PYROUTE |
| 校验引擎 | VALID | BIC/IBAN/金额/制裁名单初筛 | PYVAL |
| 账务过账 | POST | 借记/贷记、手续费、FX | PYPOST |
| 报文出站 | MSGOT | 组装并投递 SWIFT/本地清算 | PYMSGOT |
| 对账批处理 | RECON | 日终 Nostro/Vostro 对账 | PYRECON |

## 4. 关键路径（同步交易）

1. CGW 接收客户指令 → MQ `CPS.IN.Q`
2. CICS 交易 PYIN 触发 PYMAIN
3. PYVAL 校验 → AML 异步筛查 (MQ `AML.SCR.Q`)
4. PYROUTE 选路 → PYPOST 记账
5. PYMSGOT 出站 → 更新状态表 `PY_TXN_STATUS`

## 5. 非功能指标

| 指标 | 目标值 |
|------|--------|
| 联机峰值 TPS | 850 |
| P99 响应时间 | ≤ 800ms |
| 可用性 | 99.95% |
| RPO / RTO | 0 / 15min (GDPS) |
