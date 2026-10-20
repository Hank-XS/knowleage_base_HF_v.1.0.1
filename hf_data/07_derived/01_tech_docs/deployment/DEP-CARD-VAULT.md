# 部署手册：CardDemo / VAULT / zBANK 测试环境

| 文档 | DEP-CARD-VAULT-001 |
| 构件来源 | `github_cobol/carddemo` `vault_cbs` `zbank`，补齐件在 `07_derived/02_code_fill` |

## 1. 环境

| 环境 | CICS | 批 LOAD | 说明 |
|------|------|---------|------|
| TEST | CICSTEST | CARD.TEST.LOAD + VAULT.TEST.LOAD | 单 LPAR |

## 2. 发布顺序

1. COPYBOOK 进 `CARD.TEST.CPY`（CardDemo 依赖 `COSTM01` `CVACT03Y` `CUSTREC` `CVACT01Y`；VAULT 依赖 `CPYOFAC` `CPYWIRE` `CPYACCT` `CPYTXN` `CPYGL`）
2. 编译联机：`COACTUPC COCRDUPC COACTVWC COCRDLIC COCRDSLC COTRN00C COTRN02C COBIL00C CORPT00C`
3. 编译批处理：`CBTRN01C CBTRN02C CBTRN03C CBACT04C CBSTM03A`，以及补齐的 `CBSTM03B`
4. 编译 VAULT：`FILEIO0 DATEUTIL EODPROC0 EOMPROC0 WIREXFR0 ACHRECV0 TXNPOST0 GLPOST0 LOANPMT0 ACCTMGMT`
5. `CEDA INSTALL GROUP(CARDDEMO)` 见 `CARDDEMO_CSD.txt`
6. 提交 JCL `CBSTM03A#`、`VAULTEOD#`
7. 冒烟：CB00 还款一笔；`WIREXFR0` function=INQY；`ZBNKBANK` 登录后转账

## 3. 已知缺口（部署必看）

| 缺口 | 影响 | 处理 |
|------|------|------|
| 仓库未带 `CBSTM03B` | `CBSTM03A` 的 CALL 无法链接 | 使用 `02_code_fill/cobol/CBSTM03B.cbl` |
| `OFACCHK0` `FEECALC0` `INTCALC0` `AUDTLOG0` 行数不足未入库 | `WIREXFR0`/`EODPROC0` 链接失败 | 测试桩 `VAULTSTUB.cbl` |
| CardDemo COPYBOOK 未随本次拉取 | 编译报 COPY 找不到 | 从上游 carddemo `app/cpy` 另取，或只做静态分析不编译 |

## 4. 回退

`CEMT SET PROGRAM(COACTUPC) NEWCOPY` 回上一 LOAD。批处理保留上一代 `CARD.TEST.LOAD.BAK`。
