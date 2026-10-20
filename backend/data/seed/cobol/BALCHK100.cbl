      *==============================================================*
      * BALCHK100 - BALANCE CHECK COMMON ROUTINE                     *
      * 通用余额校验子程序（被 ATMWD402 等交易调用）                  *
      *==============================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BALCHK100.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 CHK-RESULT          PIC X(4).
       PROCEDURE DIVISION.
       1000-CHECK SECTION.
           PERFORM 1100-LOAD-FROZEN.
           PERFORM 1200-COMPARE.
       1100-LOAD-FROZEN SECTION.
           EXEC SQL SELECT FROZEN_AMT INTO :WS-FROZEN
                    FROM CUSTOMER WHERE ACCT_NUM = :ACCT-NUM
           END-EXEC.
       1200-COMPARE SECTION.
           IF AVAIL-BAL >= TRAN-AMT MOVE 'PASS' TO CHK-RESULT
           ELSE MOVE 'FAIL' TO CHK-RESULT.
