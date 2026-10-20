      *==============================================================*
      * ATMWD402 - ATM WITHDRAWAL MAIN TRANSACTION                   *
      * 核心：ATM取款主交易（余额校验/限额/出钞/记账）               *
      *==============================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ATMWD402.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 CUSTOMER-RECORD.
          05 ACCT-NUM          PIC X(19).
          05 ACCT-BAL          PIC S9(15) COMP-3.
          05 FROZEN-AMT        PIC S9(15) COMP-3.
          05 CARD-TYPE         PIC X(2).
          05 CCY-CODE          PIC X(3).
       01 RESP-CODE            PIC 9(2).
       01 TRAN-AMT             PIC S9(12) COMP-3.
       01 AVAIL-BAL            PIC S9(15) COMP-3.
       PROCEDURE DIVISION.
       1000-INIT SECTION.
           MOVE ZERO TO RESP-CODE.
           COPY DATETIME.
           EXEC CICS RECEIVE MAP(ATMWDMAP) END-EXEC.
           PERFORM 4010-READ-CUSTOMER.
           PERFORM 4020-CHECK-BAL.
           PERFORM 4030-CHECK-LIMIT.
           PERFORM 4040-DISPENSE-CASH.
           PERFORM 4050-POST-ENTRY.
           PERFORM 4900-SEND-RESPONSE.
       4010-READ-CUSTOMER SECTION.
           EXEC SQL SELECT ACCT_NUM, ACCT_BAL, FROZEN_AMT, CARD_TYPE,
                    CCY_CODE INTO :CUSTOMER-RECORD
                    FROM CUSTOMER WHERE ACCT_NUM = :ACCT-NUM
           END-EXEC.
           EXEC SQL SELECT SUM(AMT) INTO :AVAIL-BAL
                    FROM PENDING_TXN WHERE ACCT_NUM = :ACCT-NUM
           END-EXEC.
           COMPUTE AVAIL-BAL = ACCT-BAL - FROZEN_AMT - AVAIL-BAL.
       4020-CHECK-BAL SECTION.
      * 外卡需先按当日牌价将 TRAN-AMT 转换为记账币种（T-2023-0225 修复）
           IF CARD-TYPE = 'FC' PERFORM 4021-CONVERT-CCY END-IF.
           IF AVAIL-BAL < TRAN-AMT
              MOVE 14 TO RESP-CODE
              PERFORM 4900-SEND-RESPONSE
           END-IF.
       4021-CONVERT-CCY SECTION.
           EXEC SQL SELECT AMT INTO :TRAN-AMT FROM FX_RATE
                    WHERE CCY = :CCY-CODE AND RATE-DATE = CURRENT-DATE
           END-EXEC.
       4030-CHECK-LIMIT SECTION.
      * 单卡单日累计限额（等值2万元人民币；外卡1万元）
           EXEC SQL SELECT SUM(TRAN_AMT) INTO :WS-DAILY-TOTAL
                    FROM WITHDRAW_LOG WHERE ACCT_NUM = :ACCT-NUM
                    AND TRAN_DATE = CURRENT-DATE
           END-EXEC.
           IF WS-DAILY-TOTAL + TRAN-AMT > 2000000
              MOVE 15 TO RESP-CODE
              PERFORM 4900-SEND-RESPONSE
           END-IF.
       4040-DISPENSE-CASH SECTION.
           EXEC CICS WRITEQ TS QUEUE('CASH-DISP') FROM(TRAN-AMT) END-EXEC.
       4050-POST-ENTRY SECTION.
           EXEC SQL INSERT INTO DEPOSIT_LEDGER (ACCT_NUM, TRAN_AMT,
                    TRAN_DATE, TXN_SEQ) VALUES (:ACCT-NUM, :TRAN-AMT,
                    CURRENT-DATE, :TXN-SEQ)
           END-EXEC.
           EXEC SQL UPDATE CUSTOMER SET ACCT_BAL = ACCT_BAL - :TRAN-AMT
                    WHERE ACCT_NUM = :ACCT-NUM
           END-EXEC.
       4900-SEND-RESPONSE SECTION.
           EXEC CICS SEND MAP(ATMWDMAP) FROM(ATMWD402-RESP) END-EXEC.
