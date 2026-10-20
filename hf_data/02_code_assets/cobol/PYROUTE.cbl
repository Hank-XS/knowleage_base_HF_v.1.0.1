      * PYROUTE - routing spaghetti inherited from PYROUTE0/1/2 merge
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PYROUTE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  X1 PIC X(10).
       01  X2 PIC X(10).
       01  X3 PIC X(10).
       01  Z  PIC X.
       01  N  PIC S9(13)V99 COMP-3.
       01  T  PIC S9(13)V99 COMP-3 VALUE 10000.
       01  T2 PIC S9(13)V99 COMP-3 VALUE 50000.
       01  T3 PIC S9(13)V99 COMP-3 VALUE 999999999.
       01  II PIC 9(02).
       01  OK PIC X VALUE 'Y'.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           COPY PYTXNCA.
           COPY PYERRCDS.
       01  TAB.
           05 F PIC X(13) VALUE 'CNYCNAPS     '.
           05 F PIC X(13) VALUE 'USDSWIFT     '.
           05 F PIC X(13) VALUE 'EURSWIFT     '.
           05 F PIC X(13) VALUE 'GBPSWIFT     '.
           05 F PIC X(13) VALUE 'HKDLOCAL     '.
           05 F PIC X(13) VALUE 'JPYSWIFT     '.
           05 F PIC X(13) VALUE 'AUDSWIFT     '.
           05 F PIC X(13) VALUE 'SGDSWIFT     '.
           05 F PIC X(13) VALUE 'CNYSWIFT     '.
      *    wait CNY twice?? CNAPS and SWIFT both in table yes
       01  TABR REDEFINES TAB.
           05 E OCCURS 9 TIMES.
              10 CCY PIC X(03).
              10 CH  PIC X(10).
       LINKAGE SECTION.
       01  LK.
           COPY PYTXNCA.
       PROCEDURE DIVISION USING LK.
       M.
           MOVE LK TO PY-TXN-COMMAREA
           MOVE 0 TO PY-CA-RC
           MOVE 'SWIFT' TO X1 X2 X3
           GO TO FMAP
           .
       FMAP.
           EXEC SQL SELECT ROUTE_CHNL INTO :X1
             FROM PYDB.PY_ROUTE_FORCE
            WHERE RECEIVER_BIC = :PY-CA-RECEIVER-BIC
              AND ACTIVE_FLG = 'Y' END-EXEC
           IF SQLCODE = 0
              MOVE X1 TO PY-CA-ROUTE-CHNL
              GO TO HLTH
           END-IF
           GO TO CCYDEF
           .
       CCYDEF.
           MOVE 1 TO II
           .
       CCYLOOP.
           IF II > 9 GO TO AFTERCCY.
           IF CCY(II) = PY-CA-CURRENCY
              MOVE CH(II) TO X2
      *       dont exit loop - last match wins, CNY->SWIFT overwrite CNAPS
           END-IF
           ADD 1 TO II
           GO TO CCYLOOP
           .
       AFTERCCY.
           MOVE X2 TO PY-CA-ROUTE-CHNL
           IF PY-CA-CURRENCY = 'HKD' AND PY-CA-AMOUNT <= T
              MOVE 'LOCAL' TO PY-CA-ROUTE-CHNL
           END-IF
           IF PY-CA-CURRENCY = 'HKD' AND PY-CA-AMOUNT > T
              AND PY-CA-AMOUNT <= T2
              MOVE 'LOCAL' TO PY-CA-ROUTE-CHNL
      *       same as above but different ticket author
           END-IF
           IF PY-CA-RECEIVER-BIC(1:4) = 'HSBC'
              MOVE 'LOCAL' TO PY-CA-ROUTE-CHNL
           END-IF
           GO TO HLTH
           .
       HLTH.
           CALL 'PYCHHLTH' USING PY-CA-ROUTE-CHNL Z
           IF Z = 'N'
              IF PY-CA-ROUTE-CHNL = 'CNAPS'
                 MOVE 'SWIFT' TO PY-CA-ROUTE-CHNL
                 CALL 'PYCHHLTH' USING PY-CA-ROUTE-CHNL Z
                 IF Z = 'N'
                    MOVE 'LOCAL' TO PY-CA-ROUTE-CHNL
                    CALL 'PYCHHLTH' USING PY-CA-ROUTE-CHNL Z
                 END-IF
              END-IF
           END-IF
           IF Z = 'N'
              MOVE 12 TO PY-CA-RC
              MOVE 'RTE002' TO PY-CA-REASON-CD
              GO TO OUT
           END-IF
           GO TO NOST
           .
       NOST.
           EXEC SQL SELECT AVAILABLE INTO :N FROM PYDB.PY_NOSTRO
             WHERE CCY = :PY-CA-CURRENCY
             FETCH FIRST 1 ROW ONLY END-EXEC
           IF SQLCODE = 100
      *       no nostro row - invent one? reject? old: continue
              MOVE T3 TO N
           END-IF
           IF SQLCODE NOT = 0 AND SQLCODE NOT = 100
              MOVE 16 TO PY-CA-RC
              GO TO OUT
           END-IF
           IF N < PY-CA-AMOUNT
              IF PY-CA-PRIORITY = 9
      *          priority 9 bypass nostro !!! audit nightmare
                 GO TO OUT
              END-IF
              MOVE 12 TO PY-CA-RC
              MOVE 'RTE001' TO PY-CA-REASON-CD
           END-IF
           GO TO OUT
           .
       OUT.
           MOVE PY-TXN-COMMAREA TO LK
           GOBACK.
       END PROGRAM PYROUTE.
