      * PYPOST - accounting. if break you fix. - DaWei 2005
      * WARN: fee logic copy from Excel of Mary, dont ask why
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PYPOST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  A PIC S9(13)V99 COMP-3.
       01  B PIC S9(13)V99 COMP-3.
       01  C PIC S9(13)V99 COMP-3.
       01  D PIC S9(13)V99 COMP-3.
       01  E PIC S9(07)V9(06) COMP-3.
       01  F PIC S9(04) COMP.
       01  G PIC X.
       01  H PIC X(03).
       01  I PIC 9(04).
       01  J PIC 9(04).
       01  FEE1 PIC S9(13)V99 COMP-3 VALUE 0.
       01  FEE2 PIC S9(13)V99 COMP-3 VALUE 0.
       01  FEE3 PIC S9(13)V99 COMP-3 VALUE 0.
       01  FEE-FINAL PIC S9(13)V99 COMP-3 VALUE 0.
      * rates hardcode - FX table "too slow" said boss 2014
       01  R-USDHKD PIC S9V9(06) VALUE 7.800000.
       01  R-EURUSD PIC S9V9(06) VALUE 1.080000.
       01  R-GBPUSD PIC S9V9(06) VALUE 1.250000.
       01  R-CNYUSD PIC S9V9(06) VALUE 0.140000.
      * Mary update rate by hand every morning in this source????
       01  SKIP-GLS PIC X VALUE 'N'.
       01  TMP PIC X(200).
       01  SQLX PIC S9(09) COMP.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           COPY PYTXNCA.
           COPY PYERRCDS.
       LINKAGE SECTION.
       01  LK-CA.
           COPY PYTXNCA.
       PROCEDURE DIVISION USING LK-CA.
       START-HERE.
           MOVE LK-CA TO PY-TXN-COMMAREA
           MOVE 0 TO PY-CA-RC PY-CA-SQLCODE F
           MOVE PY-CA-AMOUNT TO A
           MOVE PY-CA-CURRENCY TO H
           GO TO FEE-CALC
           .
       FEE-CALC.
      *==== fee v1 ====*
           COMPUTE FEE1 = A * 0.0015
           IF FEE1 < 25 MOVE 25 TO FEE1.
           IF FEE1 > 500 MOVE 500 TO FEE1.
      *==== fee v2 somehow also run ====*
           COMPUTE FEE2 = A * 0.002
           IF H = 'CNY' COMPUTE FEE2 = FEE2 * 0.8.
           IF H = 'HKD' COMPUTE FEE2 = FEE2 * 0.5.
      *==== fee v3 from 2022 project never switch fully ====*
           IF A < 1000
              MOVE 10 TO FEE3
           ELSE
              IF A < 10000
                 MOVE 25 TO FEE3
              ELSE
                 IF A < 100000
                    MOVE 80 TO FEE3
                 ELSE
                    MOVE 200 TO FEE3
                 END-IF
              END-IF
           END-IF
      * which fee? all of them somehow
           IF H = 'USD'
              MOVE FEE1 TO FEE-FINAL
           ELSE
              IF H = 'CNY'
                 MOVE FEE2 TO FEE-FINAL
              ELSE
                 MOVE FEE3 TO FEE-FINAL
              END-IF
           END-IF
      * VIP again (copy paste from PYMAIN, not same list, beautiful)
           IF PY-CA-DEBTOR-ACCT = 'HK9999999999999999'
              MOVE 0 TO FEE-FINAL
           END-IF
           GO TO FX-BIT
           .
       FX-BIT.
           IF H = 'USD'
              MOVE A TO B
              MOVE 'N' TO PY-CA-FLG-FX
              GO TO DO-UPDATE
           END-IF
           IF H = 'HKD'
              COMPUTE B = A / R-USDHKD
              MOVE 'Y' TO PY-CA-FLG-FX
              GO TO DO-UPDATE
           END-IF
           IF H = 'EUR'
              COMPUTE B = A * R-EURUSD
              MOVE 'Y' TO PY-CA-FLG-FX
              GO TO DO-UPDATE
           END-IF
           IF H = 'GBP'
              COMPUTE B = A * R-GBPUSD
              MOVE 'Y' TO PY-CA-FLG-FX
              GO TO DO-UPDATE
           END-IF
           IF H = 'CNY'
              COMPUTE B = A * R-CNYUSD
              MOVE 'Y' TO PY-CA-FLG-FX
              GO TO DO-UPDATE
           END-IF
      * try DB2 then ignore result anyway
           EXEC SQL SELECT ASK INTO :E FROM PYDB.PY_FX_RATE
             WHERE CCY_PAIR = 'USD/HKD' END-EXEC
           MOVE A TO B
           MOVE 'N' TO PY-CA-FLG-FX
           GO TO DO-UPDATE
           .
       DO-UPDATE.
           COMPUTE C = A + FEE-FINAL
           MOVE C TO D
           EXEC SQL
             UPDATE PYDB.PY_NOSTRO
                SET AVAILABLE = AVAILABLE - :C,
                    BOOKED = BOOKED - :D
              WHERE CCY = :H
           END-EXEC
           MOVE SQLCODE TO SQLX PY-CA-SQLCODE
           IF SQLCODE = -911 GO TO RETRY-DL.
           IF SQLCODE = -913 GO TO RETRY-DL.
           IF SQLCODE = -904 GO TO RETRY-DL.
           IF SQLCODE NOT = 0
              MOVE 16 TO PY-CA-RC
              GO TO BYE
           END-IF
           GO TO INS-TXN
           .
       RETRY-DL.
           ADD 1 TO I
           IF I > 3
              MOVE 8 TO PY-CA-RC
              MOVE 'PST001' TO PY-CA-REASON-CD
              GO TO BYE
           END-IF
      * sleep? no sleep just retry hammer
           GO TO DO-UPDATE
           .
       INS-TXN.
           EXEC SQL
             INSERT INTO PYDB.PY_TXN
             (TXN_ID,UETR,MSG_TYPE,AMOUNT,CURRENCY,VALUE_DATE,
              DEBTOR_ACCT,CREDITOR_ACCT,SENDER_BIC,RECEIVER_BIC,
              ROUTE_CHNL,CREATED_TS,UPDATED_TS)
             VALUES
             (:PY-CA-TXN-ID,:PY-CA-UETR,:PY-CA-MSG-TYPE,
              :A,:H,:PY-CA-VALUE-DATE,
              :PY-CA-DEBTOR-ACCT,:PY-CA-CREDITOR-ACCT,
              :PY-CA-SENDER-BIC,:PY-CA-RECEIVER-BIC,
              :PY-CA-ROUTE-CHNL,CURRENT TIMESTAMP,CURRENT TIMESTAMP)
           END-EXEC
           IF SQLCODE = -803
              MOVE 'Y' TO PY-CA-FLG-IDEMP
              MOVE 4 TO PY-CA-RC
              GO TO GLS-MAYBE
           END-IF
           IF SQLCODE NOT = 0
              MOVE SQLCODE TO PY-CA-SQLCODE
              MOVE 16 TO PY-CA-RC
              EXEC SQL ROLLBACK END-EXEC
              GO TO BYE
           END-IF
           GO TO GLS-MAYBE
           .
       GLS-MAYBE.
           IF SKIP-GLS = 'Y'
              EXEC SQL COMMIT END-EXEC
              MOVE 0 TO PY-CA-RC
              GO TO BYE
           END-IF
      * GLS down every weekend, skip flag set by ops in memory???
           CALL 'GLPOST' USING PY-TXN-COMMAREA FEE-FINAL F
           IF F = 0
              EXEC SQL COMMIT END-EXEC
              MOVE 0 TO PY-CA-RC
           ELSE
              IF F = 4
      *          soft reject still commit ??? yes 2017 incident
                 EXEC SQL COMMIT END-EXEC
                 MOVE 4 TO PY-CA-RC
                 MOVE 'PST003' TO PY-CA-REASON-CD
              ELSE
                 EXEC SQL ROLLBACK END-EXEC
                 MOVE 16 TO PY-CA-RC
                 MOVE 'PST003' TO PY-CA-REASON-CD
              END-IF
           END-IF
           GO TO BYE
           .
       BYE.
           MOVE PY-TXN-COMMAREA TO LK-CA
           GOBACK.
       END PROGRAM PYPOST.
