       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANK-MAIN.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SESSION-FILE ASSIGN TO 'SESSION.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  SESSION-FILE.
       01 SESSION-REC.
          05 SESS-LOGGED-IN       PIC X(1).
          05 SESS-USER-NAME       PIC X(20).
          05 SESS-USER-ROLE       PIC X(1).
          05 SESS-USER-ACC        PIC 9(10).

       WORKING-STORAGE SECTION.
       01 WS-CHOICE               PIC X(2).
       01 WS-LOGGED-IN            PIC X         VALUE 'N'.
       01 WS-CURRENT-USER         PIC X(20).
       01 WS-CURRENT-ROLE         PIC X(1).
       01 WS-CURRENT-ACC          PIC 9(10).
       01 WS-LOGIN-CHOICE         PIC X.
       01 WS-CMD                  PIC X(100).
       01 WS-OS-TYPE              PIC X(10).

       PROCEDURE DIVISION.
       MAIN-START.
           PERFORM SHOW-WELCOME.
           PERFORM LOGIN-MENU UNTIL WS-LOGGED-IN = 'Y'.
      * Show menu based on role
           EVALUATE WS-CURRENT-ROLE
               WHEN 'A'
                   PERFORM ADMIN-MENU UNTIL WS-CHOICE = '99'
               WHEN 'T'
                   PERFORM TELLER-MENU UNTIL WS-CHOICE = '99'
               WHEN 'C'
                   PERFORM CUSTOMER-MENU UNTIL WS-CHOICE = '99'
           END-EVALUATE.
           PERFORM CLEANUP-SESSION.
           DISPLAY ' '.
           DISPLAY '========================================'.
           DISPLAY '  Thank you for using LedgerCOBOL!'.
           DISPLAY '  Goodbye, ' WS-CURRENT-USER '!'.
           DISPLAY '========================================'.
           DISPLAY ' '.
           STOP RUN.

       SHOW-WELCOME.
           DISPLAY ' '.
           DISPLAY '================================================'.
           DISPLAY '                                                '.
           DISPLAY '     LL      EEEEE  DDDD    GGGG  EEEEE RRRR    '.
           DISPLAY '     LL      E      D   D  G      E     R   R   '.
           DISPLAY '     LL      EEEE   D   D  G  GG  EEEE  RRRR    '.
           DISPLAY '     LL      E      D   D  G   G  E     R  R    '.
           DISPLAY '     LLLLL   EEEEE  DDDD    GGGG  EEEEE R   R   '.
           DISPLAY '                                                '.
           DISPLAY '              C O B O L                         '.
           DISPLAY '                                                '.
           DISPLAY '        Classic Core Banking System             '.
           DISPLAY '              v3.0 - Full Featured              '.
           DISPLAY '                                                '.
           DISPLAY '================================================'.
           DISPLAY ' '.

       LOGIN-MENU.
           DISPLAY '=== SYSTEM LOGIN ==='.
           DISPLAY '1. Login'.
           DISPLAY '2. Init System (First Time Setup)'.
           DISPLAY '3. Exit'.
           DISPLAY 'Option: ' WITH NO ADVANCING.
           ACCEPT WS-LOGIN-CHOICE.

           EVALUATE WS-LOGIN-CHOICE
               WHEN '1'
                   PERFORM DO-LOGIN
               WHEN '2'
                   DISPLAY ' '.
                   DISPLAY 'Initializing system databases...'.
                   CALL 'INIT-USERS'
                   CALL 'INIT-DB'
                   DISPLAY ' '.
                   DISPLAY '*** System initialized successfully! ***'
                   DISPLAY 'You can now login with default admin:'
                   DISPLAY '  Username: ADMIN'
                   DISPLAY '  PIN: 123456'
                   DISPLAY ' '
               WHEN '3'
                   DISPLAY 'Goodbye!'
                   STOP RUN
               WHEN OTHER
                   DISPLAY 'Invalid option.'
           END-EVALUATE.

       DO-LOGIN.
           CALL 'LOGIN'.
           PERFORM READ-SESSION.

       READ-SESSION.
           OPEN INPUT SESSION-FILE.
           READ SESSION-FILE
               AT END
                   MOVE 'N' TO WS-LOGGED-IN
               NOT AT END
                   IF SESS-LOGGED-IN = 'Y'
                       MOVE 'Y' TO WS-LOGGED-IN
                       MOVE SESS-USER-NAME TO WS-CURRENT-USER
                       MOVE SESS-USER-ROLE TO WS-CURRENT-ROLE
                       MOVE SESS-USER-ACC TO WS-CURRENT-ACC
                   ELSE
                       MOVE 'N' TO WS-LOGGED-IN
                   END-IF
           END-READ.
           CLOSE SESSION-FILE.

       CLEANUP-SESSION.
           ACCEPT WS-OS-TYPE FROM ENVIRONMENT 'OS'.
           IF WS-OS-TYPE = 'Windows_NT'
               MOVE 'cmd /c del SESSION.DAT 2>nul' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
           ELSE
               MOVE 'rm -f SESSION.DAT' TO WS-CMD
               CALL 'SYSTEM' USING WS-CMD
           END-IF.

      *==========================================================
      * ADMIN MENU - Full access to all features
      *==========================================================
       ADMIN-MENU.
           DISPLAY ' '.
           DISPLAY '================================================'.
           DISPLAY '            === ADMIN DASHBOARD ===             '.
           DISPLAY '================================================'.
           DISPLAY 'User: ' WS-CURRENT-USER.
           DISPLAY 'Role: Administrator'.
           DISPLAY '------------------------------------------------'.
           DISPLAY ' '.
           DISPLAY '--- User Management ---'.
           DISPLAY ' 1. Create New User'.
           DISPLAY ' 2. View All Users'.
           DISPLAY ' '.
           DISPLAY '--- Account Management ---'.
           DISPLAY ' 3. Create New Account'.
           DISPLAY ' 4. Init Account Database'.
           DISPLAY ' '.
           DISPLAY '--- Transactions ---'.
           DISPLAY ' 5. Deposit / Withdraw'.
           DISPLAY ' 6. Transfer Between Accounts'.
           DISPLAY ' 7. Transaction History'.
           DISPLAY ' '.
           DISPLAY '--- Reports ---'.
           DISPLAY ' 8. Account Balance Report'.
           DISPLAY ' '.
           DISPLAY '--- Settings ---'.
           DISPLAY ' 9. Change My PIN'.
           DISPLAY ' '.
           DISPLAY '99. Logout & Exit'.
           DISPLAY ' '.
           DISPLAY 'Option: ' WITH NO ADVANCING.
           ACCEPT WS-CHOICE.

           EVALUATE WS-CHOICE
               WHEN '1'
                   CALL 'CREATE-USER'
               WHEN '2'
                   CALL 'LIST-USERS'
               WHEN '3'
                   CALL 'CREATE-ACC'
               WHEN '4'
                   CALL 'INIT-DB'
               WHEN '5'
                   CALL 'TRANS-PROC'
               WHEN '6'
                   CALL 'TRANSFER'
               WHEN '7'
                   CALL 'HISTORY'
               WHEN '8'
                   CALL 'REPORT-GEN'
               WHEN '9'
                   CALL 'CHANGE-PIN'
               WHEN '99'
                   DISPLAY ' '
                   DISPLAY 'Logging out...'
               WHEN OTHER
                   DISPLAY 'Invalid option.'
           END-EVALUATE.

      *==========================================================
      * TELLER MENU - Customer management & transactions
      *==========================================================
       TELLER-MENU.
           DISPLAY ' '.
           DISPLAY '================================================'.
           DISPLAY '           === TELLER DASHBOARD ===             '.
           DISPLAY '================================================'.
           DISPLAY 'User: ' WS-CURRENT-USER.
           DISPLAY 'Role: Teller'.
           DISPLAY '------------------------------------------------'.
           DISPLAY ' '.
           DISPLAY '--- Customer Service ---'.
           DISPLAY ' 1. Create New Customer (User)'.
           DISPLAY ' 2. Create New Account'.
           DISPLAY ' '.
           DISPLAY '--- Transactions ---'.
           DISPLAY ' 3. Deposit / Withdraw'.
           DISPLAY ' 4. Transfer Between Accounts'.
           DISPLAY ' 5. Transaction History'.
           DISPLAY ' '.
           DISPLAY '--- Reports ---'.
           DISPLAY ' 6. Account Balance Report'.
           DISPLAY ' '.
           DISPLAY '--- Settings ---'.
           DISPLAY ' 7. Change My PIN'.
           DISPLAY ' '.
           DISPLAY '99. Logout & Exit'.
           DISPLAY ' '.
           DISPLAY 'Option: ' WITH NO ADVANCING.
           ACCEPT WS-CHOICE.

           EVALUATE WS-CHOICE
               WHEN '1'
                   CALL 'CREATE-USER'
               WHEN '2'
                   CALL 'CREATE-ACC'
               WHEN '3'
                   CALL 'TRANS-PROC'
               WHEN '4'
                   CALL 'TRANSFER'
               WHEN '5'
                   CALL 'HISTORY'
               WHEN '6'
                   CALL 'REPORT-GEN'
               WHEN '7'
                   CALL 'CHANGE-PIN'
               WHEN '99'
                   DISPLAY ' '
                   DISPLAY 'Logging out...'
               WHEN OTHER
                   DISPLAY 'Invalid option.'
           END-EVALUATE.

      *==========================================================
      * CUSTOMER MENU - Limited to own account only
      *==========================================================
       CUSTOMER-MENU.
           DISPLAY ' '.
           DISPLAY '================================================'.
           DISPLAY '          === CUSTOMER DASHBOARD ===            '.
           DISPLAY '================================================'.
           DISPLAY 'User   : ' WS-CURRENT-USER.
           DISPLAY 'Role   : Customer'.
           DISPLAY 'Account: ' WS-CURRENT-ACC.
           DISPLAY '------------------------------------------------'.
           DISPLAY ' '.
           DISPLAY '--- Banking Services ---'.
           DISPLAY ' 1. Deposit / Withdraw'.
           DISPLAY ' 2. Transfer to Another Account'.
           DISPLAY ' 3. View My Balance'.
           DISPLAY ' 4. My Transaction History'.
           DISPLAY ' '.
           DISPLAY '--- Settings ---'.
           DISPLAY ' 5. Change My PIN'.
           DISPLAY ' '.
           DISPLAY '99. Logout & Exit'.
           DISPLAY ' '.
           DISPLAY 'Option: ' WITH NO ADVANCING.
           ACCEPT WS-CHOICE.

           EVALUATE WS-CHOICE
               WHEN '1'
                   CALL 'TRANS-PROC'
               WHEN '2'
                   CALL 'TRANSFER'
               WHEN '3'
                   CALL 'REPORT-GEN'
               WHEN '4'
                   CALL 'HISTORY'
               WHEN '5'
                   CALL 'CHANGE-PIN'
               WHEN '99'
                   DISPLAY ' '
                   DISPLAY 'Logging out...'
               WHEN OTHER
                   DISPLAY 'Invalid option.'
           END-EVALUATE.
