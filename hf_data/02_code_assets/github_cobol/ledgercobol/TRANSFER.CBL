       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANSFER.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO 'ACCOUNTS.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT TEMP-FILE ASSIGN TO 'ACCOUNTS.TMP'
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT HISTORY-FILE ASSIGN TO 'HISTORY.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT SESSION-FILE ASSIGN TO 'SESSION.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
       01 ACCOUNT-REC.
          05 REC-ACC-NUMBER    PIC 9(10).
          05 REC-ACC-NAME      PIC X(30).
          05 REC-ACC-BALANCE   PIC S9(13)V99.
          05 REC-ACC-STATUS    PIC X(1).

       FD  TEMP-FILE.
       01 TEMP-REC.
          05 TEMP-ACC-NUMBER   PIC 9(10).
          05 TEMP-ACC-NAME     PIC X(30).
          05 TEMP-ACC-BALANCE  PIC S9(13)V99.
          05 TEMP-ACC-STATUS   PIC X(1).

       FD  HISTORY-FILE.
       01 HISTORY-REC.
          05 HIST-DATE         PIC 9(8).
          05 HIST-TIME         PIC 9(6).
          05 HIST-FROM-ACC     PIC 9(10).
          05 HIST-TO-ACC       PIC 9(10).
          05 HIST-TYPE         PIC X(1).
          05 HIST-AMOUNT       PIC S9(13)V99.
          05 HIST-STATUS       PIC X(1).

       FD  SESSION-FILE.
       01 SESSION-REC.
          05 SESS-LOGGED-IN    PIC X(1).
          05 SESS-USER-NAME    PIC X(20).
          05 SESS-USER-ROLE    PIC X(1).
          05 SESS-USER-ACC     PIC 9(10).

       WORKING-STORAGE SECTION.
       01 WS-EOF-FLAG          PIC X         VALUE 'N'.
       01 WS-FROM-ACC          PIC 9(10).
       01 WS-TO-ACC            PIC 9(10).
       01 WS-AMOUNT            PIC 9(13)V99.
       01 WS-FROM-FOUND        PIC X         VALUE 'N'.
       01 WS-TO-FOUND          PIC X         VALUE 'N'.
       01 WS-FROM-BALANCE      PIC S9(13)V99.
       01 WS-TO-BALANCE        PIC S9(13)V99.
       01 WS-FROM-NAME         PIC X(30).
       01 WS-TO-NAME           PIC X(30).
       01 WS-CMD               PIC X(100).
       01 WS-OS-TYPE           PIC X(10).
       01 WS-CURRENT-DATE.
          05 WS-YEAR           PIC 9(4).
          05 WS-MONTH          PIC 9(2).
          05 WS-DAY            PIC 9(2).
       01 WS-CURRENT-TIME.
          05 WS-HOUR           PIC 9(2).
          05 WS-MIN            PIC 9(2).
          05 WS-SEC            PIC 9(2).
       01 WS-DATE-NUM          PIC 9(8).
       01 WS-TIME-NUM          PIC 9(6).
       01 WS-FORMATTED-AMT     PIC $$$,$$$,$$$,$$9.99.
       01 WS-USER-ROLE         PIC X(1).
       01 WS-USER-ACC          PIC 9(10).

       PROCEDURE DIVISION.
       MAIN-PROCEDURE.
      * Read session to check role and account
           PERFORM READ-SESSION.

           DISPLAY ' '.
           DISPLAY '========================================'.
           DISPLAY '        TRANSFER BETWEEN ACCOUNTS       '.
           DISPLAY '========================================'.
           DISPLAY ' '.

      * If customer, auto-fill from account
           IF WS-USER-ROLE = 'C'
               MOVE WS-USER-ACC TO WS-FROM-ACC
               DISPLAY 'From Account: ' WS-FROM-ACC ' (Your Account)'
           ELSE
               DISPLAY 'From Account Number: ' WITH NO ADVANCING
               ACCEPT WS-FROM-ACC
           END-IF.

           DISPLAY 'To Account Number: ' WITH NO ADVANCING.
           ACCEPT WS-TO-ACC.
           DISPLAY 'Amount: ' WITH NO ADVANCING.
           ACCEPT WS-AMOUNT.

      * Validate same account
           IF WS-FROM-ACC = WS-TO-ACC
               DISPLAY ' '
               DISPLAY '*** ERROR: Cannot transfer to same account! ***'
               STOP RUN
           END-IF.

      * Validate amount
           IF WS-AMOUNT <= 0
               DISPLAY ' '
               DISPLAY '*** ERROR: Amount must be greater than 0! ***'
               STOP RUN
           END-IF.

           DISPLAY ' '.
           DISPLAY 'Processing transfer...'.

      * First pass - validate accounts exist and check balance
           OPEN INPUT ACCOUNT-FILE.
           MOVE 'N' TO WS-EOF-FLAG.
           MOVE 'N' TO WS-FROM-FOUND.
           MOVE 'N' TO WS-TO-FOUND.

           PERFORM UNTIL WS-EOF-FLAG = 'Y'
               READ ACCOUNT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       PERFORM VALIDATE-ACCOUNTS
               END-READ
           END-PERFORM.
           CLOSE ACCOUNT-FILE.

      * Check validation results
           IF WS-FROM-FOUND = 'N'
               DISPLAY '*** ERROR: Source account not found! ***'
               STOP RUN
           END-IF.

           IF WS-TO-FOUND = 'N'
               DISPLAY '*** ERROR: Destination account not found! ***'
               STOP RUN
           END-IF.

           IF WS-FROM-BALANCE < WS-AMOUNT
               DISPLAY '*** ERROR: Insufficient balance! ***'
               DISPLAY 'Available: ' WS-FROM-BALANCE
               STOP RUN
           END-IF.

      * Second pass - perform transfer
           OPEN INPUT ACCOUNT-FILE.
           OPEN OUTPUT TEMP-FILE.
           MOVE 'N' TO WS-EOF-FLAG.

           PERFORM UNTIL WS-EOF-FLAG = 'Y'
               READ ACCOUNT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF-FLAG
                   NOT AT END
                       PERFORM PROCESS-TRANSFER
               END-READ
           END-PERFORM.

           CLOSE ACCOUNT-FILE.
           CLOSE TEMP-FILE.

      * Replace old file
           ACCEPT WS-OS-TYPE FROM ENVIRONMENT 'OS'.
           IF WS-OS-TYPE = 'Windows_NT'
               MOVE 'cmd /c del ACCOUNTS.DAT 2>nul' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
               MOVE 'cmd /c ren ACCOUNTS.TMP ACCOUNTS.DAT' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
           ELSE
               MOVE 'rm -f ACCOUNTS.DAT' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
               MOVE 'mv ACCOUNTS.TMP ACCOUNTS.DAT' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
           END-IF.

      * Log transaction to history
           PERFORM LOG-TRANSACTION.

      * Display success
           MOVE WS-AMOUNT TO WS-FORMATTED-AMT.
           DISPLAY ' '.
           DISPLAY '========================================'.
           DISPLAY '       TRANSFER SUCCESSFUL!            '.
           DISPLAY '========================================'.
           DISPLAY ' '.
           DISPLAY 'From    : ' WS-FROM-ACC ' (' 
               WS-FROM-NAME ')'.
           DISPLAY 'To      : ' WS-TO-ACC ' (' 
               WS-TO-NAME ')'.
           DISPLAY 'Amount  : ' WS-FORMATTED-AMT.
           DISPLAY ' '.
           DISPLAY '========================================'.

           STOP RUN.

       READ-SESSION.
           OPEN INPUT SESSION-FILE.
           READ SESSION-FILE
               AT END
                   MOVE 'A' TO WS-USER-ROLE
                   MOVE 0 TO WS-USER-ACC
               NOT AT END
                   MOVE SESS-USER-ROLE TO WS-USER-ROLE
                   MOVE SESS-USER-ACC TO WS-USER-ACC
           END-READ.
           CLOSE SESSION-FILE.

       VALIDATE-ACCOUNTS.
           IF REC-ACC-NUMBER = WS-FROM-ACC
               MOVE 'Y' TO WS-FROM-FOUND
               MOVE REC-ACC-BALANCE TO WS-FROM-BALANCE
               MOVE REC-ACC-NAME TO WS-FROM-NAME
           END-IF.
           IF REC-ACC-NUMBER = WS-TO-ACC
               MOVE 'Y' TO WS-TO-FOUND
               MOVE REC-ACC-BALANCE TO WS-TO-BALANCE
               MOVE REC-ACC-NAME TO WS-TO-NAME
           END-IF.

       PROCESS-TRANSFER.
           IF REC-ACC-NUMBER = WS-FROM-ACC
               SUBTRACT WS-AMOUNT FROM REC-ACC-BALANCE
           END-IF.
           IF REC-ACC-NUMBER = WS-TO-ACC
               ADD WS-AMOUNT TO REC-ACC-BALANCE
           END-IF.
           MOVE ACCOUNT-REC TO TEMP-REC.
           WRITE TEMP-REC.

       LOG-TRANSACTION.
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE
               WS-CURRENT-TIME.
           STRING WS-YEAR WS-MONTH WS-DAY DELIMITED BY SIZE
               INTO WS-DATE-NUM.
           STRING WS-HOUR WS-MIN WS-SEC DELIMITED BY SIZE
               INTO WS-TIME-NUM.

           OPEN EXTEND HISTORY-FILE.
           MOVE WS-DATE-NUM TO HIST-DATE.
           MOVE WS-TIME-NUM TO HIST-TIME.
           MOVE WS-FROM-ACC TO HIST-FROM-ACC.
           MOVE WS-TO-ACC TO HIST-TO-ACC.
           MOVE 'T' TO HIST-TYPE.
           MOVE WS-AMOUNT TO HIST-AMOUNT.
           MOVE 'S' TO HIST-STATUS.
           WRITE HISTORY-REC.
           CLOSE HISTORY-FILE.
