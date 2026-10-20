      * TEMP FIX FOR PROD ISSUE 2020-03-15 COVID VOL SPIKE
      * "we remove after weekend" - still in LOAD as of 2024
      * called from PYMAIN via CALL 'FIXTMP1' under weird condition
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIXTMP1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W PIC X(100).
       01  N PIC 9(07) VALUE 0.
       LINKAGE SECTION.
       01  L PIC X(4096).
       PROCEDURE DIVISION USING L.
           ADD 1 TO N
           IF N > 999999 MOVE 0 TO N.
      *    just delay a bit "reduce deadlock"
           MOVE L(1:17) TO W
           IF W(1:3) = 'CPS'
              CONTINUE
           ELSE
              MOVE 'CPS' TO W(1:3)
           END-IF
      *    mutate txn id prefix if missing - silent data fix
           MOVE W TO L(1:17)
           GOBACK.
