# 架构设计书：CardDemo + VAULT-CBS + zBANK 组合域

| 字段 | 值 |
|------|-----|
| 文档编号 | ARCH-CARD-VAULT-001 |
| 依据源码 | `02_code_assets/github_cobol/` |
| 性质 | 由现有程序反推的测试用架构，不是上游官方设计书 |

## 1. 三个子系统

| 子系统 | 入口程序 | 运行时 | 职责 |
|--------|----------|--------|------|
| CardDemo | `COACTUPC` / `COTRN00C` / `COBIL00C` / `CBSTM03A` | CICS + 批处理 VSAM | 信用卡账户、卡片、交易、账单、账单打印 |
| VAULT-CBS | `EODPROC0` / `WIREXFR0` / `ACHRECV0` / `FILEIO0` | 批处理 COBOL 子程序 | 电汇、ACH、贷款、总账、日终/月末 |
| zBANK | `ZBNKBANK` | CICS LINK 或 GnuCOBOL CALL | 登录、存取转、VSAM 账户 |
| LedgerCOBOL | `BANK-MAIN` | GnuCOBOL CALL | 柜面菜单：开户、转账、历史 |

## 2. 分层（从源码调用归纳）

```
联机 CICS
  COACTUPC 账户更新 (~3860行)  COCRDUPC 卡片更新
  COACTVWC 账户浏览            COCRDLIC / COCRDSLC 卡片列表
  COTRN00C --XCTL--> 交易列表   COTRN02C 记交易 + CALL CSUTLDTC
  COBIL00C TRANID=CB00 账单还款，文件 TRANSACT，XCTL 返回菜单
  CORPT00C 报表 + CALL CSUTLDTC

批处理
  CBTRN01C/02C/03C  CBACT04C  交易/账户过账
  CBSTM03A 账单文本+HTML
      CALL CBSTM03B  (操作码 O/C/R/K/W/Z，COMMAREA WS-M03B-AREA)
      失败 CALL CEE3ABD

VAULT 日终 EODPROC0
  CALL INTCALC0 计息
  CALL TXNPOST0 过账
  CALL GLPOST0  总账试算
  CALL AUDTLOG0 审计
月末 EOMPROC0
  CALL FEECALC0 / TXNPOST0 / AUDTLOG0
电汇 WIREXFR0  功能 SEND/RECV/COMP/RVRS/INQY
  CALL OFACCHK0
  双人授权阈值 WS-DUAL-CONTROL-THRESHOLD = 50000.00
ACH ACHRECV0
  CALL REGDCHK0 / OFACCHK0 / AUDTLOG0
文件网关 FILEIO0  被各模块读写共用

zBANK
  ZBNKBANK CALL/LINK ZBNKAUTH
  ZBNKBANK CALL/LINK ZBNKTXN  (DATASET READ/REWRITE/WRITE)
```

## 3. 数据存储

| 存储 | 使用程序 | 形态 |
|------|----------|------|
| VSAM `ACCTDAT` `CARDDAT` `CUSTDAT` `TRANSACT` `CXACAIX` | CardDemo 联机/批 | KSDS |
| 顺序 `TRNXFILE` `STMTFILE` `HTMLFILE` | `CBSTM03A` / `CBSTM03B` | PS |
| VAULT 索引文件（账户/电汇/贷款/GL） | `FILEIO0` 及业务模块 | 索引文件 |
| zBANK VSAM 账户 + 交易历史 | `ZBNKTXN` | KSDS |

## 4. 跨系统边界

CardDemo 的账单还款 `COBIL00C` 不直接调 VAULT。测试环境用 MQ `CARD.PAY.OUT` 把还款事件交给 `ACHRECV0` / `TXNPOST0`，电汇大额走 `WIRE.OUT` 给 `WIREXFR0`。这是补齐的集成点，源码里没有这条 MQ，文档里标明为测试桩。
