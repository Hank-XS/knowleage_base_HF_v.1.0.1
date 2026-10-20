# 需求规格说明书（由源码反推）

| 文档 | SRS-CARD-VAULT-001 |
| 依据 | CardDemo CBL、VAULT `WIREXFR0`/`ACHRECV0`/`EODPROC0`、zBANK、Ledger `BANK-MAIN` |

## 功能需求

| ID | 规则 | 源码位置 |
|----|------|----------|
| FR-01 | 账户更新必须过字段编辑（金额、字母、必填、Y/N） | `COACTUPC` WS-GENERIC-EDITS |
| FR-02 | 账单还款交易号为 CB00，写入 `TRANSACT`，完成后 XCTL 回菜单 | `COBIL00C` |
| FR-03 | 新增交易前调用日期子程序 | `COTRN02C` `CALL CSUTLDTC` |
| FR-04 | 账单批处理同时出 80 字节文本和 100 字节 HTML | `CBSTM03A` FD |
| FR-05 | 交易文件只能经 `CBSTM03B` 打开，操作码 O/C/R/K/W/Z | `CBSTM03A` WS-M03B-OPER |
| FR-06 | 账单金额不平则 `CALL CEE3ABD` | `CBSTM03A` |
| FR-07 | 电汇功能仅 SEND/RECV/COMP/RVRS/INQY | `WIREXFR0` EVALUATE |
| FR-08 | 电汇金额大于 50000 需双人授权 | `WS-DUAL-CONTROL-THRESHOLD` |
| FR-09 | 汇出/汇入都要 `CALL OFACCHK0` | `WIREXFR0` 两处 CALL |
| FR-10 | ACH 入账前做 Reg D 与 OFAC，并写审计 | `ACHRECV0` |
| FR-11 | 日终顺序：计息、过账、总账试算、审计 | `EODPROC0` |
| FR-12 | 试算借贷必须平衡 | `WS-TB-IS-BALANCED` |
| FR-13 | 月末另计费用再过账 | `EOMPROC0` CALL `FEECALC0` |
| FR-14 | zBANK 先认证再做存取转 | `ZBNKBANK` CALL `ZBNKAUTH` 然后 `ZBNKTXN` |
| FR-15 | 柜面转账从菜单进入 | `BANK-MAIN` CALL `TRANSFER` |

## 非功能

联机程序走 CICS，批处理走 JCL。`COACTUPC` 单程序约 4000 行，变更要单独回归账户更新画面。
