# GitHub COBOL Banking Sources（仅收录 ≥200 行）

拉取时间用于测试/分析；保留上游版权与许可。短文件（&lt;200 行）已丢弃。

| 目录 | 仓库 | 许可 | 说明 |
|------|------|------|------|
| `carddemo/` | [aws-samples/aws-mainframe-modernization-carddemo](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) | Apache-2.0 | AWS CardDemo：信用卡账户/交易/账单/用户管理 CICS COBOL |
| `vault_cbs/` | [NSEvent/cobol-banking-system](https://github.com/NSEvent/cobol-banking-system) | 上游未标 SPDX（用前核对 LICENSE） | VAULT-CBS：电汇/ACH/贷款/总账/日终等 |
| `zbank/` | [LeviLucena/zBANK](https://github.com/LeviLucena/zBANK) | 上游未标 SPDX | CICS/VSAM 银行账户模拟 |
| `ledgercobol/` | [revengerrr/LedgerCOBOL](https://github.com/revengerrr/LedgerCOBOL) | MIT | 核心银行转账/主控 |
| `omp_course/` | [openmainframeproject/cobol-programming-course](https://github.com/openmainframeproject/cobol-programming-course) | 见上游 LICENSE | OMP 课程：DB2 进阶实验 |

## 筛选规则

- 关键词：cobol + banking / card / payment / wire / ACH / DB2
- 扩展名：`.cbl` / `.CBL` / `.cob`
- **行数 &lt; 200 不要**（含短 SP/模块/测试桩）
- 未收录：教程级几十行样例、未完成 REXX、纯 copybook

## 本次增补（约 200–650 行）

- `carddemo/CBACT01C.cbl` ~409 · `CBEXPORT.cbl` ~549 · `CBIMPORT.cbl` ~455
- `carddemo/COUSR00C.cbl` ~612 · `COUSR01C.cbl` ~259 · `COUSR02C.cbl` ~366 · `COUSR03C.cbl` ~315
- `carddemo/COADM01C.cbl` ~286 · `COMEN01C.cbl` ~266 · `COTRN01C.cbl` ~288
- `carddemo/CODATE01.cbl` ~524 · `COPAUS1C.cbl` ~505 · `COPAUS2C.cbl` ~244
- `carddemo/CBPAUP0C.cbl` ~356 · `COBTUPDT.cbl` ~237
- `omp_course/CBLDB22.cbl` ~201（DB2）

## 体量最大（节选）

- `carddemo/COACTUPC.cbl` ~3860 行（账户更新）
- `carddemo/COCRDUPC.cbl` ~1560 行（卡片更新）
- `vault_cbs/FILEIO0.cob` ~469 行 / `WIREXFR0.cob` ~393 行 / `ACHRECV0.cob` ~371 行
