      *==============================================================*
      * INTCALC - INTEREST CALCULATION BATCH PROGRAM                 *
      * 利息计提批处理（T-2022-0611 缺陷修复：四舍五入规则）          *
      *==============================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTCALC.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 INT-RATE            PIC S9(3)V9(6) COMP-3.
       PROCEDURE DIVISION.
       1000-INIT SECTION.
           PERFORM 2000-LOAD-RATE.
           PERFORM 3000-CALC-INTEREST.
           PERFORM 4000-POST-INTEREST.
       2000-LOAD-RATE SECTION.
           EXEC SQL SELECT RATE INTO :INT-RATE FROM INT_RATE_TABLE
                    WHERE CCY = 'CNY' AND TERM = '01'
           END-EXEC.
       3000-CALC-INTEREST SECTION.
      * 修复点：利息计算结果按分四舍五入（ROUNDED）
           COMPUTE WS-INTEREST ROUNDED = ACCT-BAL * INT-RATE / 365.
       4000-POST-INTEREST SECTION.
           EXEC SQL INSERT INTO DEPOSIT_LEDGER (ACCT_NUM, TRAN_AMT,
                    TRAN_TYPE) VALUES (:ACCT-NUM, :WS-INTEREST, 'INT')
           END-EXEC.
