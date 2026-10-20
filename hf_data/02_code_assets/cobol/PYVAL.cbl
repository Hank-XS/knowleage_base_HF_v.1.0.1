      *===============================================================*
      * PROGRAM-ID.  PYVAL                                             *
      * DESC........ Field validation: IBAN MOD97, BIC, ccy whitelist, *
      *              amount decimals per ISO4217, value-date calendar  *
      *===============================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PYVAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IBAN               PIC X(34).
       01  WS-IBAN-NORM          PIC X(68).
       01  WS-MOD-WORK           PIC 9(18).
       01  WS-MOD-REM            PIC 9(02).
       01  WS-I                  PIC S9(04) COMP.
       01  WS-J                  PIC S9(04) COMP.
       01  WS-CHAR               PIC X.
       01  WS-DIGIT              PIC 9(02).
       01  WS-DEC-PLACES         PIC 9 VALUE 2.
       01  WS-AMT-INT            PIC 9(13).
       01  WS-AMT-DEC            PIC 9(03).
       01  WS-CCY-OK             PIC X VALUE 'N'.
       01  WS-WHITELIST          PIC X(32)
           VALUE 'USDEURGBPHKDCNYJPYAUDSGD'.

           COPY PYTXNCA.
           COPY PYERRCDS.

       LINKAGE SECTION.
       01  LK-CA.
           COPY PYTXNCA.

       PROCEDURE DIVISION USING LK-CA.
       0000-MAIN.
           MOVE LK-CA TO PY-TXN-COMMAREA
           MOVE PY-RC-OK TO PY-CA-RC
           PERFORM 1000-CCY-WHITELIST
           IF PY-CA-RC NOT = PY-RC-OK PERFORM 9000-EXIT END-IF
           PERFORM 2000-AMOUNT-CHECK
           IF PY-CA-RC NOT = PY-RC-OK PERFORM 9000-EXIT END-IF
           PERFORM 3000-BIC-CHECK
           IF PY-CA-RC NOT = PY-RC-OK PERFORM 9000-EXIT END-IF
           PERFORM 4000-IBAN-IF-APPLICABLE
           IF PY-CA-RC NOT = PY-RC-OK PERFORM 9000-EXIT END-IF
           PERFORM 5000-VALUE-DATE
           PERFORM 9000-EXIT
           .

       1000-CCY-WHITELIST.
           MOVE 'N' TO WS-CCY-OK
           PERFORM VARYING WS-I FROM 1 BY 3 UNTIL WS-I > 30
              IF WS-WHITELIST(WS-I:3) = PY-CA-CURRENCY
                 MOVE 'Y' TO WS-CCY-OK
                 MOVE 99 TO WS-I
              END-IF
           END-PERFORM
           IF WS-CCY-OK = 'N'
              MOVE 'VAL002' TO PY-CA-REASON-CD
              MOVE PY-RC-REJECT TO PY-CA-RC
           END-IF
           .

       2000-AMOUNT-CHECK.
           IF PY-CA-AMOUNT <= 0
              MOVE 'VAL003' TO PY-CA-REASON-CD
              MOVE PY-RC-REJECT TO PY-CA-RC
              GO TO 2000-EXIT
           END-IF
           EVALUATE PY-CA-CURRENCY
              WHEN 'JPY' WHEN 'KRW'
                 MOVE 0 TO WS-DEC-PLACES
              WHEN 'KWD' WHEN 'BHD' WHEN 'OMR'
                 MOVE 3 TO WS-DEC-PLACES
              WHEN OTHER
                 MOVE 2 TO WS-DEC-PLACES
           END-EVALUATE
           COMPUTE WS-AMT-INT = FUNCTION INTEGER(PY-CA-AMOUNT)
           COMPUTE WS-AMT-DEC =
              FUNCTION INTEGER(
                 (PY-CA-AMOUNT - WS-AMT-INT)
                 * FUNCTION EXP10(WS-DEC-PLACES) + 0.00001)
      *    JPY must have zero fractional part
           IF WS-DEC-PLACES = 0
              AND PY-CA-AMOUNT NOT = WS-AMT-INT
              MOVE 'VAL003' TO PY-CA-REASON-CD
              MOVE PY-RC-REJECT TO PY-CA-RC
           END-IF
           .
       2000-EXIT.
           EXIT.

       3000-BIC-CHECK.
           IF FUNCTION LENGTH(FUNCTION TRIM(PY-CA-RECEIVER-BIC))
              < 8
              MOVE 'VAL004' TO PY-CA-REASON-CD
              MOVE PY-RC-REJECT TO PY-CA-RC
           END-IF
           .

       4000-IBAN-IF-APPLICABLE.
           MOVE PY-CA-CREDITOR-ACCT TO WS-IBAN
           IF WS-IBAN(1:2) IS NOT ALPHABETIC
              GO TO 4000-EXIT
           END-IF
           PERFORM 4100-IBAN-MOD97
           IF WS-MOD-REM NOT = 1
              MOVE 'VAL001' TO PY-CA-REASON-CD
              MOVE PY-RC-REJECT TO PY-CA-RC
           END-IF
           .
       4000-EXIT.
           EXIT.

       4100-IBAN-MOD97.
      *    Rearrange: move first 4 chars to end, A=10..Z=35, mod 97
           MOVE SPACES TO WS-IBAN-NORM
           STRING WS-IBAN(5:) DELIMITED BY SPACE
                  WS-IBAN(1:4) DELIMITED BY SIZE
                  INTO WS-IBAN-NORM
           END-STRING
           MOVE 0 TO WS-MOD-WORK
           PERFORM VARYING WS-I FROM 1 BY 1
              UNTIL WS-I > 68 OR WS-IBAN-NORM(WS-I:1) = SPACE
              MOVE WS-IBAN-NORM(WS-I:1) TO WS-CHAR
              IF WS-CHAR >= '0' AND WS-CHAR <= '9'
                 COMPUTE WS-MOD-WORK =
                    FUNCTION MOD(WS-MOD-WORK * 10
                       + FUNCTION NUMVAL(WS-CHAR) 97)
              ELSE
                 IF WS-CHAR >= 'A' AND WS-CHAR <= 'Z'
                    COMPUTE WS-DIGIT =
                       FUNCTION ORD(WS-CHAR)
                       - FUNCTION ORD('A') + 10
                    COMPUTE WS-MOD-WORK =
                       FUNCTION MOD(WS-MOD-WORK * 100 + WS-DIGIT 97)
                 END-IF
              END-IF
           END-PERFORM
           MOVE WS-MOD-WORK TO WS-MOD-REM
           .

       5000-VALUE-DATE.
      *    Stub: call calendar service; fail open with warn in test data
           IF PY-CA-VALUE-DATE = SPACES
              MOVE 'VAL005' TO PY-CA-REASON-CD
              MOVE PY-RC-REJECT TO PY-CA-RC
           END-IF
           .

       9000-EXIT.
           MOVE PY-TXN-COMMAREA TO LK-CA
           GOBACK
           .
       END PROGRAM PYVAL.
