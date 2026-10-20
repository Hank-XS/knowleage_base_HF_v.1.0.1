IDENTIFICATION DIVISION.
PROGRAM-ID. EODPROC0.
*> ================================================================
*> EODPROC0 - End-of-Day Batch Orchestrator
*> Processes all active accounts: interest accrual, hold release,
*> CTR aggregation, trial balance verification
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
COPY CPYCONST.

*> Hold/CTR processing
COPY CPYHOLD.
COPY CPYCTR.

*> INTCALC0 result area
01  WS-INT-RESULT.
    05  WS-INT-RESULT-CODE      PIC X(5).
    05  WS-INT-RESULT-MSG       PIC X(50).
    05  WS-DAILY-INT-AMT        PIC S9(11)V9(6).
    05  WS-NEW-ACCRUED          PIC S9(11)V9(6).
    05  WS-PAYMENT-AMT          PIC S9(11)V99.
    05  WS-PAYMENT-DUE          PIC X(1).

*> TXNPOST0 areas
COPY CPYTXN.
01  WS-GL-ENTRIES.
    05  WS-GL-DR-ACCOUNT       PIC 9(10).
    05  WS-GL-CR-ACCOUNT       PIC 9(10).
    05  WS-GL-AMOUNT           PIC S9(13)V99.
    05  WS-GL-POST-FLAG        PIC X(1).
01  WS-TXN-RESULT.
    05  WS-TXN-RESULT-CODE    PIC X(5).
    05  WS-TXN-RESULT-MSG     PIC X(50).

*> GLPOST0 areas
01  WS-GL-FUNCTION             PIC X(4).
01  WS-GL-ENTRY.
    05  WS-GLE-DR-ACCT         PIC 9(10).
    05  WS-GLE-CR-ACCT         PIC 9(10).
    05  WS-GLE-AMOUNT          PIC S9(15)V99.
    05  WS-GLE-DESCRIPTION     PIC X(40).
    05  WS-GLE-POST-DATE       PIC 9(8).
COPY CPYGL.
01  WS-TRIAL-BAL.
    05  WS-TB-TOTAL-DEBITS     PIC S9(15)V99.
    05  WS-TB-TOTAL-CREDITS    PIC S9(15)V99.
    05  WS-TB-DIFFERENCE       PIC S9(15)V99.
    05  WS-TB-IS-BALANCED      PIC X(1).
01  WS-GL-RESULT.
    05  WS-GL-RESULT-CODE      PIC X(5).
    05  WS-GL-RESULT-MSG       PIC X(50).

*> HOLDCALC0 areas
01  WS-HOLD-REQUEST.
    05  WS-HR-ACCT-NUMBER      PIC 9(12).
    05  WS-HR-DEPOSIT-AMT      PIC S9(13)V99.
    05  WS-HR-CHECK-TYPE        PIC X(2).
    05  WS-HR-DEPOSIT-DATE      PIC 9(8).
    05  WS-HR-ACCT-OPEN-DATE    PIC 9(8).
    05  WS-HR-IS-REDEPOSIT      PIC X(1).
    05  WS-HR-REPEATED-OD       PIC X(1).
01  WS-HOLD-RESULT.
    05  WS-HOLD-RESULT-CODE    PIC X(5).
    05  WS-HOLD-RESULT-MSG     PIC X(50).
    05  WS-HOLD-NEXT-DAY-AMT   PIC S9(13)V99.
    05  WS-HOLD-REMAINING-AMT  PIC S9(13)V99.
    05  WS-HOLD-RELEASE-DT     PIC 9(8).
    05  WS-HOLD-EXCEPTION-FLAG PIC X(1).

*> BSA/AML areas
01  WS-BSA-FUNCTION            PIC X(4).
01  WS-TXN-INFO.
    05  WS-BSA-CUST-ID         PIC 9(10).
    05  WS-BSA-TXN-DATE        PIC 9(8).
    05  WS-BSA-CASH-AMOUNT     PIC S9(13)V99.
    05  WS-BSA-CASH-DIRECTION  PIC X(1).
    05  WS-BSA-IS-CASH         PIC X(1).
    05  WS-BSA-ACCT-NUMBER     PIC 9(12).
01  WS-BSA-RESULT.
    05  WS-BSA-RESULT-CODE     PIC X(5).
    05  WS-BSA-RESULT-MSG      PIC X(50).
    05  WS-BSA-CTR-REQUIRED    PIC X(1).
    05  WS-BSA-CASH-IN-TOTAL   PIC S9(13)V99.
    05  WS-BSA-CASH-OUT-TOTAL  PIC S9(13)V99.

*> Audit areas
01  WS-AUDIT-FUNCTION          PIC X(4).
COPY CPYAUDT.
01  WS-AUDIT-RESULT.
    05  WS-AUDT-RESULT-CODE   PIC X(5).
    05  WS-AUDT-RESULT-MSG    PIC X(50).

*> Next-pay-date advancement work fields
01  WS-NP-DATE                 PIC 9(8).
01  WS-NP-YYYY                PIC 9(4).
01  WS-NP-MM                  PIC 9(2).
01  WS-NP-DD                  PIC 9(2).
01  WS-NP-MONTHS-TO-ADD       PIC 9(2).
01  WS-NP-LEAP-REM4           PIC 9(4).
01  WS-NP-LEAP-REM100         PIC 9(4).
01  WS-NP-LEAP-REM400         PIC 9(4).

*> Rollback fields for interest posting failure
01  WS-SAVE-ACCRUED-INT        PIC S9(11)V9(6).
01  WS-SAVE-YTD-INT-PAID       PIC S9(11)V99.
01  WS-SAVE-YTD-INT-EARNED     PIC S9(11)V9(6).
01  WS-SAVE-PTD-INT-EARNED     PIC S9(11)V9(6).
01  WS-SAVE-NP-DATE             PIC 9(8).

*> Batch control
01  WS-ACCTS-PROCESSED        PIC 9(8) VALUE 0.
01  WS-ACCTS-ERRORS           PIC 9(8) VALUE 0.
01  WS-TOTAL-INT-ACCRUED      PIC S9(15)V99 VALUE 0.
01  WS-TOTAL-INT-PAID         PIC S9(15)V99 VALUE 0.
01  WS-HOLDS-RELEASED         PIC 9(8) VALUE 0.

LINKAGE SECTION.
01  LS-BATCH-DATE              PIC 9(8).
COPY CPYACCT.
COPY CPYBATCH.
01  LS-BATCH-RESULT.
    05  LS-BATCH-RESULT-CODE   PIC X(5).
    05  LS-BATCH-RESULT-MSG    PIC X(50).

PROCEDURE DIVISION USING LS-BATCH-DATE
                         ACCT-RECORD
                         BATCH-RECORD
                         LS-BATCH-RESULT.
MAIN-LOGIC.
    MOVE "E0000" TO LS-BATCH-RESULT-CODE
    MOVE SPACES TO LS-BATCH-RESULT-MSG
    MOVE 0 TO WS-ACCTS-PROCESSED
    MOVE 0 TO WS-ACCTS-ERRORS
    MOVE 0 TO WS-TOTAL-INT-ACCRUED
    MOVE 0 TO WS-TOTAL-INT-PAID
    MOVE 0 TO WS-HOLDS-RELEASED

    *> Update batch control record
    MOVE LS-BATCH-DATE TO BATCH-DATE
    MOVE "EOD" TO BATCH-TYPE
    MOVE "S" TO BATCH-STATUS

    *> Process provided account
    *> Active, Dormant, and Frozen accounts all need EOD processing.
    *> Frozen accounts still accrue interest (freeze blocks transactions,
    *> not interest entitlement). Interest payment posting may fail for
    *> frozen accounts, which is handled by the rollback logic.
    IF ACCT-STATUS = "A" OR ACCT-STATUS = "D"
        OR ACCT-STATUS = "F"
        PERFORM PROCESS-ACCOUNT
    END-IF

    *> Trial balance verification
    INITIALIZE WS-GL-ENTRY
    INITIALIZE GL-RECORD
    INITIALIZE WS-TRIAL-BAL
    INITIALIZE WS-GL-RESULT
    MOVE "TBAL" TO WS-GL-FUNCTION
    CALL "GLPOST0" USING WS-GL-FUNCTION
                         WS-GL-ENTRY
                         GL-RECORD
                         WS-TRIAL-BAL
                         WS-GL-RESULT
    IF WS-GL-RESULT-CODE = "E0000"
        IF WS-TB-IS-BALANCED = "N"
            ADD 1 TO WS-ACCTS-ERRORS
        END-IF
    ELSE
        ADD 1 TO WS-ACCTS-ERRORS
    END-IF

    *> Write batch summary
    MOVE WS-ACCTS-PROCESSED TO BATCH-ACCTS-PROCESSED
    MOVE WS-ACCTS-ERRORS TO BATCH-ACCTS-ERRORS
    MOVE WS-TOTAL-INT-ACCRUED TO BATCH-INT-ACCRUED
    MOVE WS-TOTAL-INT-PAID TO BATCH-INT-PAID
    MOVE WS-HOLDS-RELEASED TO BATCH-HOLDS-RELEASED

    IF WS-ACCTS-ERRORS = 0
        MOVE "C" TO BATCH-STATUS
        MOVE "E0000" TO LS-BATCH-RESULT-CODE
        MOVE "EOD batch completed successfully"
            TO LS-BATCH-RESULT-MSG
    ELSE
        MOVE "P" TO BATCH-STATUS
        MOVE "E0003" TO LS-BATCH-RESULT-CODE
        MOVE "EOD batch completed with errors"
            TO LS-BATCH-RESULT-MSG
    END-IF
    GOBACK.

*> ---------------------------------------------------------------
*> Process a single account for EOD
*> ---------------------------------------------------------------
PROCESS-ACCOUNT.
    ADD 1 TO WS-ACCTS-PROCESSED

    *> Step 1: Accrue daily interest
    PERFORM EOD-ACCRUE-INTEREST

    *> Step 2: Check if interest payment is due
    IF WS-PAYMENT-DUE = "Y"
        PERFORM EOD-POST-INTEREST-PAYMENT
    END-IF

    *> Step 3: Release matured holds
    PERFORM EOD-RELEASE-HOLDS

    *> Step 4: CTR aggregation
    *> Note: CTR aggregation for cash transactions is handled at the
    *> transaction level by TXNPOST0 via CHECK-CTR in BSACTRO.
    *> EOD simply reports batch totals via BATCH-CTR-FILED.

    *> Step 5: Log audit trail
    PERFORM EOD-LOG-AUDIT.

*> ---------------------------------------------------------------
*> Accrue daily interest via INTCALC0
*> ---------------------------------------------------------------
EOD-ACCRUE-INTEREST.
    INITIALIZE WS-INT-RESULT
    *> Save pre-INTCALC0 values for rollback if payment posting fails
    MOVE ACCT-ACCRUED-INT TO WS-SAVE-ACCRUED-INT
    MOVE ACCT-YTD-INT-PAID TO WS-SAVE-YTD-INT-PAID
    MOVE ACCT-YTD-INT-EARNED TO WS-SAVE-YTD-INT-EARNED
    MOVE ACCT-PTD-INT-EARNED TO WS-SAVE-PTD-INT-EARNED
    CALL "INTCALC0" USING ACCT-RECORD
                          LS-BATCH-DATE
                          WS-INT-RESULT
    IF WS-INT-RESULT-CODE = "E0000"
        ADD WS-DAILY-INT-AMT TO WS-TOTAL-INT-ACCRUED
            ON SIZE ERROR
                MOVE "E0040" TO LS-BATCH-RESULT-CODE
                MOVE "Arithmetic overflow on total interest accrued"
                    TO LS-BATCH-RESULT-MSG
                GOBACK
        END-ADD
    ELSE
        MOVE WS-SAVE-ACCRUED-INT TO ACCT-ACCRUED-INT
        MOVE WS-SAVE-YTD-INT-PAID TO ACCT-YTD-INT-PAID
        MOVE WS-SAVE-YTD-INT-EARNED TO ACCT-YTD-INT-EARNED
        MOVE WS-SAVE-PTD-INT-EARNED TO ACCT-PTD-INT-EARNED
        ADD 1 TO WS-ACCTS-ERRORS
    END-IF.

*> ---------------------------------------------------------------
*> Post interest payment as a transaction
*> ---------------------------------------------------------------
EOD-POST-INTEREST-PAYMENT.
    INITIALIZE TXN-RECORD
    INITIALIZE WS-GL-ENTRIES
    INITIALIZE WS-TXN-RESULT
    MOVE ACCT-NUMBER TO TXN-ACCT-NUMBER
    MOVE "INT" TO TXN-TYPE
    MOVE "C" TO TXN-DR-CR
    MOVE WS-PAYMENT-AMT TO TXN-AMOUNT
    MOVE LS-BATCH-DATE TO TXN-POST-DATE
    MOVE LS-BATCH-DATE TO TXN-EFFECTIVE-DATE
    MOVE "SYSTEM" TO TXN-TELLER-ID
    MOVE "SY" TO TXN-CHANNEL
    CALL "TXNPOST0" USING TXN-RECORD
                          ACCT-RECORD
                          WS-GL-ENTRIES
                          WS-TXN-RESULT
    IF WS-TXN-RESULT-CODE = "E0000"
        ADD WS-PAYMENT-AMT TO WS-TOTAL-INT-PAID
            ON SIZE ERROR
                MOVE "E0040" TO LS-BATCH-RESULT-CODE
                MOVE "Arithmetic overflow on total interest paid"
                    TO LS-BATCH-RESULT-MSG
                GOBACK
        END-ADD
        PERFORM ADVANCE-NEXT-PAY-DATE
    ELSE
        *> Rollback: restore accrued interest + today's daily,
        *> and restore YTD-INT-PAID (payment didn't happen).
        *> DO NOT restore YTD-INT-EARNED or PTD-INT-EARNED —
        *> INTCALC0 correctly added today's daily interest to them,
        *> and the interest was earned regardless of whether the
        *> payment was successfully posted.
        MOVE WS-SAVE-ACCRUED-INT TO ACCT-ACCRUED-INT
        ADD WS-DAILY-INT-AMT TO ACCT-ACCRUED-INT
            ON SIZE ERROR
                CONTINUE
        END-ADD
        MOVE WS-SAVE-YTD-INT-PAID TO ACCT-YTD-INT-PAID
        *> Advance next-pay-date even on failure to prevent infinite
        *> retry on every subsequent EOD run. Accrued interest is
        *> preserved and will be paid on the next payment cycle.
        PERFORM ADVANCE-NEXT-PAY-DATE
        ADD 1 TO WS-ACCTS-ERRORS
    END-IF.

*> ---------------------------------------------------------------
*> Advance ACCT-INT-NEXT-PAY-DATE based on payment frequency
*> ---------------------------------------------------------------
ADVANCE-NEXT-PAY-DATE.
    IF ACCT-INT-NEXT-PAY-DATE = 0
        CONTINUE
    ELSE
        *> Determine months to add from frequency
        EVALUATE ACCT-INT-PAY-FREQ
            WHEN "M"
                MOVE 1 TO WS-NP-MONTHS-TO-ADD
            WHEN "Q"
                MOVE 3 TO WS-NP-MONTHS-TO-ADD
            WHEN "S"
                MOVE 6 TO WS-NP-MONTHS-TO-ADD
            WHEN "A"
                MOVE 12 TO WS-NP-MONTHS-TO-ADD
            WHEN "T"
                *> At Maturity: do not advance pay date
                *> Interest held until maturity (CD/term deposit)
                CONTINUE
            WHEN OTHER
                MOVE 1 TO WS-NP-MONTHS-TO-ADD
        END-EVALUATE
        IF ACCT-INT-PAY-FREQ = "T"
            *> Skip date arithmetic for at-maturity frequency
            GO TO ADVANCE-NEXT-PAY-DATE-EXIT
        END-IF
        *> Save original date for rollback on overflow
        MOVE ACCT-INT-NEXT-PAY-DATE TO WS-SAVE-NP-DATE
        *> Decompose YYYYMMDD into parts
        MOVE ACCT-INT-NEXT-PAY-DATE TO WS-NP-DATE
        DIVIDE WS-NP-DATE BY 10000
            GIVING WS-NP-YYYY
            REMAINDER WS-NP-DATE
        DIVIDE WS-NP-DATE BY 100
            GIVING WS-NP-MM
            REMAINDER WS-NP-DD
        *> Add months
        ADD WS-NP-MONTHS-TO-ADD TO WS-NP-MM
        *> Roll over year if needed
        PERFORM UNTIL WS-NP-MM <= 12
            SUBTRACT 12 FROM WS-NP-MM
            ADD 1 TO WS-NP-YYYY
        END-PERFORM
        *> Cap day for shorter months
        IF WS-NP-DD > 28
            EVALUATE WS-NP-MM
                WHEN 2
                    DIVIDE WS-NP-YYYY BY 4
                        GIVING WS-NP-LEAP-REM4
                        REMAINDER WS-NP-LEAP-REM4
                    DIVIDE WS-NP-YYYY BY 100
                        GIVING WS-NP-LEAP-REM100
                        REMAINDER WS-NP-LEAP-REM100
                    DIVIDE WS-NP-YYYY BY 400
                        GIVING WS-NP-LEAP-REM400
                        REMAINDER WS-NP-LEAP-REM400
                    IF WS-NP-LEAP-REM4 = 0
                        AND (WS-NP-LEAP-REM100 NOT = 0
                             OR WS-NP-LEAP-REM400 = 0)
                        MOVE 29 TO WS-NP-DD
                    ELSE
                        MOVE 28 TO WS-NP-DD
                    END-IF
                WHEN 4
                WHEN 6
                WHEN 9
                WHEN 11
                    IF WS-NP-DD > 30
                        MOVE 30 TO WS-NP-DD
                    END-IF
            END-EVALUATE
        END-IF
        *> Recompose date
        COMPUTE ACCT-INT-NEXT-PAY-DATE =
            WS-NP-YYYY * 10000
            + WS-NP-MM * 100
            + WS-NP-DD
            ON SIZE ERROR
                MOVE WS-SAVE-NP-DATE TO ACCT-INT-NEXT-PAY-DATE
                ADD 1 TO WS-ACCTS-ERRORS
        END-COMPUTE
    END-IF.

ADVANCE-NEXT-PAY-DATE-EXIT.
    EXIT.

*> ---------------------------------------------------------------
*> Log EOD processing to audit trail
*> ---------------------------------------------------------------
EOD-LOG-AUDIT.
    INITIALIZE AUDIT-RECORD
    INITIALIZE WS-AUDIT-RESULT
    MOVE "WRIT" TO WS-AUDIT-FUNCTION
    MOVE "SYSTEM" TO AUDIT-USER-ID
    MOVE "EODPROC0" TO AUDIT-PROGRAM-ID
    MOVE "EOD " TO AUDIT-FUNCTION
    MOVE "ACCT" TO AUDIT-ENTITY-TYPE
    MOVE ACCT-NUMBER TO AUDIT-ENTITY-KEY
    MOVE "E0000" TO AUDIT-RESULT-CODE
    MOVE "EOD processing complete" TO AUDIT-DESCRIPTION
    CALL "AUDTLOG0" USING WS-AUDIT-FUNCTION
                          AUDIT-RECORD
                          WS-AUDIT-RESULT.

*> ---------------------------------------------------------------
*> Release matured holds on account
*> Uses ACCT-HOLD-RELEASE-DT from the account record to determine
*> if the hold has matured. Callers of HOLDCALC0 must copy
*> LS-HOLD-RELEASE-DT to ACCT-HOLD-RELEASE-DT when placing holds.
*> When ACCT-HOLD-RELEASE-DT = 0, the hold is not auto-released.
*> ---------------------------------------------------------------
EOD-RELEASE-HOLDS.
    IF ACCT-HOLD-AMOUNT > 0
        *> Only release if hold has matured (release date <= batch date)
        *> Skip release when: no release date set (0) or date is future
        IF ACCT-HOLD-RELEASE-DT = 0
            OR ACCT-HOLD-RELEASE-DT > LS-BATCH-DATE
            *> Hold has no release date or has not yet matured
            CONTINUE
        ELSE
            MOVE 0 TO ACCT-HOLD-AMOUNT
            MOVE 0 TO ACCT-HOLD-RELEASE-DT
            COMPUTE ACCT-AVAIL-BAL =
                ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
                ON SIZE ERROR
                    ADD 1 TO WS-ACCTS-ERRORS
            END-COMPUTE
            ADD 1 TO WS-HOLDS-RELEASED
        END-IF
    END-IF
    *> Reset daily NSF counter for next business day
    MOVE 0 TO ACCT-NSF-COUNT-TODAY.
