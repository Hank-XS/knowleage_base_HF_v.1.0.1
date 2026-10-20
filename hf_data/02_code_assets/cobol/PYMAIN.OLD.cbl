      * PYMAIN.OLD - DO NOT USE - but STEPLIB still has it in LOADLIB3
      * last compile 2011-03-22
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PYMAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TXN PIC X(12).
       01  WS-AMT PIC 9(11)V99.
       01  WS-OK PIC X.
       PROCEDURE DIVISION.
           ACCEPT WS-TXN
           ACCEPT WS-AMT
           IF WS-AMT > 0 MOVE 'Y' TO WS-OK
           ELSE MOVE 'N' TO WS-OK.
           DISPLAY WS-TXN WS-OK
           STOP RUN.
