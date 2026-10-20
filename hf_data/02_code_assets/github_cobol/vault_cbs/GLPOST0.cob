IDENTIFICATION DIVISION.
PROGRAM-ID. GLPOST0.
*> ================================================================
*> GLPOST0 - General Ledger Posting and Trial Balance
*> POST = Post entry, TBAL = Trial balance, INIT = Initialize
*> CRPT = Call Report line lookup (FFIEC 041)
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-SAVE-GL-BAL               PIC S9(15)V99.
01  WS-SAVE-GL-MTD               PIC S9(15)V99.

LINKAGE SECTION.
01  LS-FUNCTION                   PIC X(4).
01  LS-GL-ENTRY.
    05  LS-GLE-DR-ACCT            PIC 9(10).
    05  LS-GLE-CR-ACCT            PIC 9(10).
    05  LS-GLE-AMOUNT             PIC S9(15)V99.
    05  LS-GLE-DESCRIPTION        PIC X(40).
    05  LS-GLE-POST-DATE          PIC 9(8).
COPY CPYGL.
01  LS-TRIAL-BAL.
    05  LS-TB-TOTAL-DEBITS        PIC S9(15)V99.
    05  LS-TB-TOTAL-CREDITS       PIC S9(15)V99.
    05  LS-TB-DIFFERENCE          PIC S9(15)V99.
    05  LS-TB-IS-BALANCED         PIC X(1).
01  LS-GL-RESULT.
    05  LS-GL-RESULT-CODE         PIC X(5).
    05  LS-GL-RESULT-MSG          PIC X(50).

PROCEDURE DIVISION USING LS-FUNCTION
                         LS-GL-ENTRY
                         GL-RECORD
                         LS-TRIAL-BAL
                         LS-GL-RESULT.

    EVALUATE LS-FUNCTION
        WHEN "POST"
            PERFORM POST-GL-ENTRY
        WHEN "TBAL"
            PERFORM TRIAL-BALANCE
        WHEN "INIT"
            PERFORM INIT-GL-RECORD
        WHEN "CRPT"
            PERFORM CALL-RPT-LOOKUP
        WHEN OTHER
            MOVE "E0001" TO LS-GL-RESULT-CODE
            MOVE "Invalid function" TO LS-GL-RESULT-MSG
    END-EVALUATE
    GOBACK.

*> ----------------------------------------------------------------
*> POST-GL-ENTRY - Post one side of a double-entry GL journal
*> ----------------------------------------------------------------
*> IMPORTANT: Double-entry bookkeeping requires two POST calls per
*> journal entry - one for the debit-side GL account and one for the
*> credit-side GL account. The caller is responsible for ensuring
*> both sides are posted. Use TBAL to verify trial balance.
*>
*> Example (caller pseudocode):
*>   1. CALL GLPOST0 "POST" with GL-RECORD = debit account
*>   2. CALL GLPOST0 "POST" with GL-RECORD = credit account
*>   3. CALL GLPOST0 "TBAL" to verify debits = credits
*> ----------------------------------------------------------------
POST-GL-ENTRY.
    *> Check account status
    IF GL-STATUS = "I"
        MOVE "E0061" TO LS-GL-RESULT-CODE
        MOVE "Account inactive" TO LS-GL-RESULT-MSG
        EXIT PARAGRAPH
    END-IF
    IF GL-STATUS = "F"
        MOVE "E0062" TO LS-GL-RESULT-CODE
        MOVE "Account frozen" TO LS-GL-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    *> Check for zero amount
    IF LS-GLE-AMOUNT = ZERO
        MOVE "E0063" TO LS-GL-RESULT-CODE
        MOVE "Zero posting amount" TO LS-GL-RESULT-MSG
        EXIT PARAGRAPH
    END-IF
    *> Check for negative amount
    IF LS-GLE-AMOUNT < ZERO
        MOVE "E0064" TO LS-GL-RESULT-CODE
        MOVE "Negative posting amount" TO LS-GL-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    *> Update GL-RECORD based on normal balance direction.
    *> Determine if this GL account is on the debit or credit side
    *> of the journal entry by comparing GL-ACCOUNT-NUM against
    *> the entry's DR/CR account numbers. This replaces the prior
    *> heuristic (LS-GLE-DR-ACCT > LS-GLE-CR-ACCT) which failed
    *> for FEE and INT transactions.
    EVALUATE GL-NORMAL-BALANCE
        WHEN "D"
            *> Debit-normal account (Asset, Expense)
            IF GL-ACCOUNT-NUM = LS-GLE-CR-ACCT
                *> This debit-normal account is on the CR side
                *> (credit decreases debit-normal balance)
                MOVE GL-CURRENT-BAL TO WS-SAVE-GL-BAL
                SUBTRACT LS-GLE-AMOUNT FROM GL-CURRENT-BAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on GL balance"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-SUBTRACT
                MOVE GL-MTD-CREDITS TO WS-SAVE-GL-MTD
                ADD LS-GLE-AMOUNT TO GL-MTD-CREDITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on MTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
                ADD LS-GLE-AMOUNT TO GL-YTD-CREDITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE WS-SAVE-GL-MTD TO GL-MTD-CREDITS
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on YTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
            ELSE
                *> Debit-normal account on DR side (or GL-ACCOUNT-NUM
                *> not set — default to debit for backwards compat)
                MOVE GL-CURRENT-BAL TO WS-SAVE-GL-BAL
                ADD LS-GLE-AMOUNT TO GL-CURRENT-BAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on GL balance"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
                MOVE GL-MTD-DEBITS TO WS-SAVE-GL-MTD
                ADD LS-GLE-AMOUNT TO GL-MTD-DEBITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on MTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
                ADD LS-GLE-AMOUNT TO GL-YTD-DEBITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE WS-SAVE-GL-MTD TO GL-MTD-DEBITS
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on YTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
            END-IF
        WHEN "C"
            *> Credit-normal account (Liability, Income, Equity)
            IF GL-ACCOUNT-NUM = LS-GLE-DR-ACCT
                *> This credit-normal account is on the DR side
                *> (debit decreases credit-normal balance)
                MOVE GL-CURRENT-BAL TO WS-SAVE-GL-BAL
                SUBTRACT LS-GLE-AMOUNT FROM GL-CURRENT-BAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on GL balance"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-SUBTRACT
                MOVE GL-MTD-DEBITS TO WS-SAVE-GL-MTD
                ADD LS-GLE-AMOUNT TO GL-MTD-DEBITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on MTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
                ADD LS-GLE-AMOUNT TO GL-YTD-DEBITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE WS-SAVE-GL-MTD TO GL-MTD-DEBITS
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on YTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
            ELSE
                *> Credit-normal account on CR side (or GL-ACCOUNT-NUM
                *> not set — default to credit for backwards compat)
                MOVE GL-CURRENT-BAL TO WS-SAVE-GL-BAL
                ADD LS-GLE-AMOUNT TO GL-CURRENT-BAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on GL balance"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
                MOVE GL-MTD-CREDITS TO WS-SAVE-GL-MTD
                ADD LS-GLE-AMOUNT TO GL-MTD-CREDITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on MTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
                ADD LS-GLE-AMOUNT TO GL-YTD-CREDITS
                    ON SIZE ERROR
                        MOVE WS-SAVE-GL-BAL TO GL-CURRENT-BAL
                        MOVE WS-SAVE-GL-MTD TO GL-MTD-CREDITS
                        MOVE "E0040" TO LS-GL-RESULT-CODE
                        MOVE "Arithmetic overflow on YTD accumulator"
                            TO LS-GL-RESULT-MSG
                        GOBACK
                END-ADD
            END-IF
        WHEN OTHER
            MOVE "E0063" TO LS-GL-RESULT-CODE
            MOVE "Invalid GL normal balance indicator"
                TO LS-GL-RESULT-MSG
            GOBACK
    END-EVALUATE

    *> Map GL account to Call Report line code (12 CFR 304)
    PERFORM MAP-CALL-RPT-LINE

    *> Update last posting date
    MOVE LS-GLE-POST-DATE TO GL-LAST-POST-DATE

    MOVE "E0000" TO LS-GL-RESULT-CODE
    MOVE SPACES TO LS-GL-RESULT-MSG
    EXIT PARAGRAPH.

*> ----------------------------------------------------------------
*> TRIAL-BALANCE - Compute trial balance from debits and credits
*> ----------------------------------------------------------------
TRIAL-BALANCE.
    *> If caller hasn't set totals, read from GL-RECORD
    IF LS-TB-TOTAL-DEBITS = ZERO
        AND LS-TB-TOTAL-CREDITS = ZERO
        MOVE GL-MTD-DEBITS TO LS-TB-TOTAL-DEBITS
        MOVE GL-MTD-CREDITS TO LS-TB-TOTAL-CREDITS
    END-IF
    COMPUTE LS-TB-DIFFERENCE =
        LS-TB-TOTAL-DEBITS - LS-TB-TOTAL-CREDITS
        ON SIZE ERROR
            MOVE "E0040" TO LS-GL-RESULT-CODE
            MOVE "Arithmetic overflow on trial balance"
                TO LS-GL-RESULT-MSG
            EXIT PARAGRAPH
    END-COMPUTE
    IF LS-TB-DIFFERENCE = ZERO
        MOVE "Y" TO LS-TB-IS-BALANCED
    ELSE
        MOVE "N" TO LS-TB-IS-BALANCED
    END-IF

    MOVE "E0000" TO LS-GL-RESULT-CODE
    MOVE SPACES TO LS-GL-RESULT-MSG
    EXIT PARAGRAPH.

*> ----------------------------------------------------------------
*> INIT-GL-RECORD - Initialize a GL record with defaults
*> ----------------------------------------------------------------
INIT-GL-RECORD.
    INITIALIZE GL-RECORD
    MOVE "A" TO GL-STATUS

    MOVE "E0000" TO LS-GL-RESULT-CODE
    MOVE SPACES TO LS-GL-RESULT-MSG
    EXIT PARAGRAPH.

*> ----------------------------------------------------------------
*> MAP-CALL-RPT-LINE - Map GL account to FFIEC 041 Call Report line
*> Populates GL-CALL-RPT-LINE based on GL-ACCOUNT-NUM
*> Reference: 12 CFR 304 (Call Report / FFIEC 041)
*> ----------------------------------------------------------------
MAP-CALL-RPT-LINE.
    EVALUATE GL-ACCOUNT-NUM
        WHEN 0000001010
            MOVE "1110" TO GL-CALL-RPT-LINE
            *> Schedule RC-A: Cash and balances due
        WHEN 0000004010
            MOVE "2210" TO GL-CALL-RPT-LINE
            *> Schedule RC-E: Demand deposits (checking)
        WHEN 0000004030
            MOVE "2213" TO GL-CALL-RPT-LINE
            *> Schedule RC-E: Savings deposits
        WHEN 0000004040
            MOVE "2215" TO GL-CALL-RPT-LINE
            *> Schedule RC-E: Money market deposits
        WHEN 0000004050
            MOVE "2216" TO GL-CALL-RPT-LINE
            *> Schedule RC-E: Time deposits (CD)
        WHEN 0000007500
            MOVE "4000" TO GL-CALL-RPT-LINE
            *> Schedule RI: Fee income
        WHEN 0000008010
            MOVE "4010" TO GL-CALL-RPT-LINE
            *> Schedule RI: Interest expense
        WHEN OTHER
            MOVE "9999" TO GL-CALL-RPT-LINE
            *> Unmapped GL account
    END-EVALUATE
    EXIT PARAGRAPH.

*> ----------------------------------------------------------------
*> CALL-RPT-LOOKUP - Look up Call Report line for a GL account
*> Sets GL-CALL-RPT-LINE from GL-ACCOUNT-NUM in GL-RECORD
*> ----------------------------------------------------------------
CALL-RPT-LOOKUP.
    PERFORM MAP-CALL-RPT-LINE

    MOVE "E0000" TO LS-GL-RESULT-CODE
    MOVE SPACES TO LS-GL-RESULT-MSG
    EXIT PARAGRAPH.
