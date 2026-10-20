IDENTIFICATION DIVISION.
PROGRAM-ID. EOMPROC0.
*> ================================================================
*> EOMPROC0 - End-of-Month Batch Processor
*> Assesses monthly fees, resets MTD counters, generates statements
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
COPY CPYCONST.

*> Fee calculation areas
COPY CPYFEE.
01  WS-FEE-RESULT.
    05  WS-FEE-RESULT-CODE    PIC X(5).
    05  WS-FEE-RESULT-MSG     PIC X(50).
    05  WS-FEE-ASSESSED       PIC 9(5)V99.
    05  WS-FEE-WAIVED-FLAG    PIC X(1).
    05  WS-FEE-WAIVER-REASON  PIC X(2).

*> Transaction posting areas
COPY CPYTXN.
01  WS-GL-ENTRIES.
    05  WS-GL-DR-ACCOUNT      PIC 9(10).
    05  WS-GL-CR-ACCOUNT      PIC 9(10).
    05  WS-GL-AMOUNT          PIC S9(13)V99.
    05  WS-GL-POST-FLAG       PIC X(1).
01  WS-TXN-RESULT.
    05  WS-TXN-RESULT-CODE   PIC X(5).
    05  WS-TXN-RESULT-MSG    PIC X(50).

*> GL record for MTD reset
COPY CPYGL.

*> Audit
01  WS-AUDIT-FUNCTION         PIC X(4).
COPY CPYAUDT.
01  WS-AUDIT-RESULT.
    05  WS-AUDT-RESULT-CODE  PIC X(5).
    05  WS-AUDT-RESULT-MSG   PIC X(50).

*> Statement date calculation
01  WS-NEXT-STMT-DATE          PIC 9(8).
01  WS-NEXT-STMT-PARTS REDEFINES WS-NEXT-STMT-DATE.
    05  WS-STMT-YYYY            PIC 9(4).
    05  WS-STMT-MM              PIC 9(2).
    05  WS-STMT-DD              PIC 9(2).
01  WS-LEAP-REM4               PIC 9(4).
01  WS-LEAP-REM100             PIC 9(4).
01  WS-LEAP-REM400             PIC 9(4).

*> Year-end detection
01  WS-BATCH-MM               PIC 9(2).

*> Batch counters
01  WS-ACCTS-PROCESSED       PIC 9(8) VALUE 0.
01  WS-ACCTS-ERRORS          PIC 9(8) VALUE 0.
01  WS-TOTAL-FEES-ASSESSED   PIC S9(15)V99 VALUE 0.
01  WS-TOTAL-FEES-WAIVED     PIC S9(15)V99 VALUE 0.
01  WS-SAVE-YTD-FEES         PIC S9(11)V99.

LINKAGE SECTION.
01  LS-BATCH-DATE             PIC 9(8).
COPY CPYACCT.
COPY CPYBATCH.
01  LS-BATCH-RESULT.
    05  LS-BATCH-RESULT-CODE  PIC X(5).
    05  LS-BATCH-RESULT-MSG   PIC X(50).

PROCEDURE DIVISION USING LS-BATCH-DATE
                         ACCT-RECORD
                         BATCH-RECORD
                         LS-BATCH-RESULT.
MAIN-LOGIC.
    MOVE "E0000" TO LS-BATCH-RESULT-CODE
    MOVE SPACES TO LS-BATCH-RESULT-MSG
    MOVE 0 TO WS-ACCTS-PROCESSED
    MOVE 0 TO WS-ACCTS-ERRORS
    MOVE 0 TO WS-TOTAL-FEES-ASSESSED
    MOVE 0 TO WS-TOTAL-FEES-WAIVED

    *> Update batch control record
    MOVE LS-BATCH-DATE TO BATCH-DATE
    MOVE "EOM" TO BATCH-TYPE
    MOVE "S" TO BATCH-STATUS

    *> Process provided account
    *> Frozen accounts still need MTD counter resets, statement
    *> date advancement, and YTD resets. Fees are skipped for
    *> frozen accounts since fee posting is a debit.
    IF ACCT-STATUS = "A" OR ACCT-STATUS = "D"
        OR ACCT-STATUS = "F"
        PERFORM PROCESS-EOM-ACCOUNT
    END-IF

    *> Write batch summary
    MOVE WS-ACCTS-PROCESSED TO BATCH-ACCTS-PROCESSED
    MOVE WS-ACCTS-ERRORS TO BATCH-ACCTS-ERRORS
    MOVE WS-TOTAL-FEES-ASSESSED TO BATCH-FEES-ASSESSED

    IF WS-ACCTS-ERRORS = 0
        MOVE "C" TO BATCH-STATUS
        MOVE "E0000" TO LS-BATCH-RESULT-CODE
        MOVE "EOM batch completed successfully"
            TO LS-BATCH-RESULT-MSG
    ELSE
        MOVE "P" TO BATCH-STATUS
        MOVE "E0003" TO LS-BATCH-RESULT-CODE
        MOVE "EOM batch completed with errors"
            TO LS-BATCH-RESULT-MSG
    END-IF
    GOBACK.

*> ---------------------------------------------------------------
*> Process a single account for EOM
*> ---------------------------------------------------------------
PROCESS-EOM-ACCOUNT.
    ADD 1 TO WS-ACCTS-PROCESSED

    *> Step 0: Year-end reset - if processing January, reset previous
    *> year's YTD counters BEFORE any new-year fee/interest processing.
    *> CRITICAL: EOM must run BEFORE EOD on year-transition dates.
    *> If EOD runs first, January 1 interest accruals in YTD-INT-EARNED
    *> would be wiped by this reset. Batch orchestration must enforce
    *> the ordering: EOM(Dec) -> EOD(Jan 1) on January processing.
    COMPUTE WS-BATCH-MM =
        FUNCTION MOD(
            FUNCTION INTEGER-PART(LS-BATCH-DATE / 100), 100)
    IF WS-BATCH-MM = 1
        MOVE 0 TO ACCT-NSF-COUNT-YTD
        MOVE 0 TO ACCT-YTD-FEES-CHARGED
        MOVE 0 TO ACCT-YTD-FEES-WAIVED
        MOVE 0 TO ACCT-YTD-INT-EARNED
        MOVE 0 TO ACCT-YTD-INT-PAID
    END-IF

    *> Step 1: Assess monthly fee (skip for frozen/dormant accounts
    *> since fee posting is a debit and TXNPOST0 blocks debits
    *> for both frozen and dormant accounts)
    IF ACCT-STATUS NOT = "F" AND ACCT-STATUS NOT = "D"
        PERFORM EOM-ASSESS-FEE

        *> Step 2: Post fee if assessed
        IF WS-FEE-ASSESSED > 0
            PERFORM EOM-POST-FEE
        END-IF
    END-IF

    *> Step 3: Reset MTD counters
    PERFORM EOM-RESET-MTD

    *> Step 4: Log audit
    PERFORM EOM-LOG-AUDIT

    *> Step 5: Update statement date tracking
    PERFORM EOM-UPDATE-STMT-DATES.

*> ---------------------------------------------------------------
*> Assess monthly fee via FEECALC0
*> ---------------------------------------------------------------
EOM-ASSESS-FEE.
    INITIALIZE WS-FEE-RESULT
    *> Set up fee schedule from account product info
    INITIALIZE FEE-SCHEDULE-RECORD
    MOVE ACCT-PRODUCT-CODE TO FEE-PRODUCT-CODE
    MOVE "MTH" TO FEE-TYPE
    MOVE ACCT-MONTHLY-FEE TO FEE-AMOUNT
    MOVE "Monthly maintenance fee" TO FEE-DESCRIPTION
    MOVE "Y" TO FEE-WAIVER-ELIGIBLE
    MOVE ACCT-FEE-WAIVER-AMT TO FEE-MIN-BAL-THRESHOLD
    MOVE "A" TO FEE-STATUS
    *> Enable waiver flags so FEECALC0 can match account waiver code
    IF ACCT-FEE-WAIVER-CODE = "DD"
        MOVE "Y" TO FEE-DD-WAIVER
    END-IF
    IF ACCT-FEE-WAIVER-CODE = "EM"
        MOVE "Y" TO FEE-EMPLOYEE-WAIVER
    END-IF
    MOVE ACCT-YTD-FEES-CHARGED TO WS-SAVE-YTD-FEES
    CALL "FEECALC0" USING ACCT-RECORD
                          FEE-SCHEDULE-RECORD
                          WS-FEE-RESULT
    IF WS-FEE-RESULT-CODE = "E0000"
        IF WS-FEE-WAIVED-FLAG = "Y"
            ADD FEE-AMOUNT TO WS-TOTAL-FEES-WAIVED
        ELSE
            ADD WS-FEE-ASSESSED TO WS-TOTAL-FEES-ASSESSED
        END-IF
    ELSE
        ADD 1 TO WS-ACCTS-ERRORS
    END-IF.

*> ---------------------------------------------------------------
*> Post assessed fee as a transaction
*> ---------------------------------------------------------------
EOM-POST-FEE.
    INITIALIZE TXN-RECORD
    INITIALIZE WS-GL-ENTRIES
    INITIALIZE WS-TXN-RESULT
    MOVE ACCT-NUMBER TO TXN-ACCT-NUMBER
    MOVE "FEE" TO TXN-TYPE
    MOVE "D" TO TXN-DR-CR
    MOVE WS-FEE-ASSESSED TO TXN-AMOUNT
    MOVE LS-BATCH-DATE TO TXN-POST-DATE
    MOVE LS-BATCH-DATE TO TXN-EFFECTIVE-DATE
    MOVE "SYSTEM" TO TXN-TELLER-ID
    MOVE "SY" TO TXN-CHANNEL
    CALL "TXNPOST0" USING TXN-RECORD
                          ACCT-RECORD
                          WS-GL-ENTRIES
                          WS-TXN-RESULT
    IF WS-TXN-RESULT-CODE NOT = "E0000"
        MOVE WS-SAVE-YTD-FEES TO ACCT-YTD-FEES-CHARGED
        SUBTRACT WS-FEE-ASSESSED FROM WS-TOTAL-FEES-ASSESSED
        ADD 1 TO WS-ACCTS-ERRORS
    END-IF.

*> ---------------------------------------------------------------
*> Reset MTD counters for new month
*> ---------------------------------------------------------------
EOM-RESET-MTD.
    MOVE 0 TO ACCT-NSF-COUNT-MTD
    MOVE 0 TO ACCT-NSF-COUNT-TODAY
    MOVE 0 TO ACCT-OL-TXN-COUNT-MTD
    MOVE 0 TO ACCT-MTD-AVG-BAL
    *> Reset low-balance watermark to current balance so the new
    *> month starts tracking from here (not zero, which would make
    *> every subsequent comparison fail to detect real low points).
    MOVE ACCT-LEDGER-BAL TO ACCT-MTD-LOW-BAL.

*> ---------------------------------------------------------------
*> Log EOM processing to audit trail
*> ---------------------------------------------------------------
EOM-LOG-AUDIT.
    INITIALIZE AUDIT-RECORD
    INITIALIZE WS-AUDIT-RESULT
    MOVE "WRIT" TO WS-AUDIT-FUNCTION
    MOVE "SYSTEM" TO AUDIT-USER-ID
    MOVE "EOMPROC0" TO AUDIT-PROGRAM-ID
    MOVE "EOM " TO AUDIT-FUNCTION
    MOVE "ACCT" TO AUDIT-ENTITY-TYPE
    MOVE ACCT-NUMBER TO AUDIT-ENTITY-KEY
    MOVE "E0000" TO AUDIT-RESULT-CODE
    MOVE "EOM processing complete" TO AUDIT-DESCRIPTION
    CALL "AUDTLOG0" USING WS-AUDIT-FUNCTION
                          AUDIT-RECORD
                          WS-AUDIT-RESULT.

*> ---------------------------------------------------------------
*> Update statement date fields on account record
*> ---------------------------------------------------------------
EOM-UPDATE-STMT-DATES.
    *> Reset period-to-date interest for new statement cycle
    MOVE 0 TO ACCT-PTD-INT-EARNED
    MOVE LS-BATCH-DATE TO ACCT-LAST-STMT-DATE
    *> Set next statement date to 1 month later with rollover
    MOVE LS-BATCH-DATE TO WS-NEXT-STMT-DATE
    ADD 1 TO WS-STMT-MM
    IF WS-STMT-MM > 12
        MOVE 1 TO WS-STMT-MM
        ADD 1 TO WS-STMT-YYYY
    END-IF
    *> Cap day for shorter months to avoid invalid dates
    IF WS-STMT-DD > 28
        EVALUATE WS-STMT-MM
            WHEN 2
                DIVIDE WS-STMT-YYYY BY 4
                    GIVING WS-LEAP-REM4
                    REMAINDER WS-LEAP-REM4
                DIVIDE WS-STMT-YYYY BY 100
                    GIVING WS-LEAP-REM100
                    REMAINDER WS-LEAP-REM100
                DIVIDE WS-STMT-YYYY BY 400
                    GIVING WS-LEAP-REM400
                    REMAINDER WS-LEAP-REM400
                IF WS-LEAP-REM4 = 0
                    AND (WS-LEAP-REM100 NOT = 0
                         OR WS-LEAP-REM400 = 0)
                    MOVE 29 TO WS-STMT-DD
                ELSE
                    MOVE 28 TO WS-STMT-DD
                END-IF
            WHEN 4
            WHEN 6
            WHEN 9
            WHEN 11
                IF WS-STMT-DD > 30
                    MOVE 30 TO WS-STMT-DD
                END-IF
        END-EVALUATE
    END-IF
    MOVE WS-NEXT-STMT-DATE TO ACCT-NEXT-STMT-DATE.
