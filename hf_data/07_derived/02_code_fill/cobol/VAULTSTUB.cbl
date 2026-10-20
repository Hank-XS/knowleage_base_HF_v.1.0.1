      ******************************************************************
      * Stubs for callees referenced by vault_cbs but not kept locally
      * because those sources were under 200 lines:
      *   OFACCHK0  (WIREXFR0, ACHRECV0)
      *   FEECALC0  (EOMPROC0)
      *   INTCALC0  (EODPROC0)
      *   AUDTLOG0  (EODPROC0, EOMPROC0, ACHRECV0)
      *   REGDCHK0  (ACHRECV0)
      * Each entry is a separate PROGRAM-ID in this compilation unit
      * is NOT valid COBOL; this file is a bundle of 5 tiny programs
      * separated by END PROGRAM. Compile with cobc -m each, or split.
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OFACCHK0.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-FUNC PIC X(4).
       01  LS-RES.
           05  LS-CODE PIC X(5).
           05  LS-MSG  PIC X(50).
       PROCEDURE DIVISION USING LS-FUNC LS-RES.
           IF LS-FUNC = 'HIT '
              MOVE 'E0101' TO LS-CODE
              MOVE 'OFAC HIT (stub)' TO LS-MSG
           ELSE
              MOVE 'E0000' TO LS-CODE
              MOVE 'OFAC CLEAR (stub)' TO LS-MSG
           END-IF
           GOBACK.
       END PROGRAM OFACCHK0.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTCALC0.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-ACCT PIC X(400).
       01  LS-RES.
           05  LS-CODE PIC X(5).
           05  LS-MSG  PIC X(50).
           05  LS-DAILY PIC S9(11)V9(6) COMP-3.
           05  LS-ACCR  PIC S9(11)V9(6) COMP-3.
           05  LS-PAY   PIC S9(11)V99 COMP-3.
           05  LS-DUE   PIC X.
       PROCEDURE DIVISION USING LS-ACCT LS-RES.
           MOVE 'E0000' TO LS-CODE
           MOVE 'INT STUB 0.01' TO LS-MSG
           MOVE 0.010000 TO LS-DAILY
           MOVE 'N' TO LS-DUE
           GOBACK.
       END PROGRAM INTCALC0.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEECALC0.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-ACCT PIC X(400).
       01  LS-RES  PIC X(80).
       PROCEDURE DIVISION USING LS-ACCT LS-RES.
           MOVE 'E0000 FEE STUB WAIVED' TO LS-RES
           GOBACK.
       END PROGRAM FEECALC0.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. AUDTLOG0.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N PIC 9(9) VALUE 0.
       LINKAGE SECTION.
       01  LS-FUNC PIC X(200).
       PROCEDURE DIVISION USING LS-FUNC.
           ADD 1 TO WS-N
           GOBACK.
       END PROGRAM AUDTLOG0.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. REGDCHK0.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-ACCT PIC X(400).
       01  LS-RES  PIC X(20).
       PROCEDURE DIVISION USING LS-ACCT LS-RES.
           MOVE 'E0000 REGD OK' TO LS-RES
           GOBACK.
       END PROGRAM REGDCHK0.
