IDENTIFICATION DIVISION.
PROGRAM-ID. TXNPOST0.
*> ================================================================
*> TXNPOST0 - Transaction Posting Engine
*> Validates, authorizes, posts transactions, updates GL
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-DEPOSIT-GL            PIC 9(10).
COPY CPYCONST.

LINKAGE SECTION.
COPY CPYTXN.
COPY CPYACCT.
01  LS-GL-ENTRIES.
    05  LS-GL-DR-ACCOUNT          PIC 9(10).
    05  LS-GL-CR-ACCOUNT          PIC 9(10).
    05  LS-GL-AMOUNT              PIC S9(13)V99.
    05  LS-GL-POST-FLAG           PIC X(1).
01  LS-TXN-RESULT.
    05  LS-TXN-RESULT-CODE        PIC X(5).
    05  LS-TXN-RESULT-MSG         PIC X(50).

PROCEDURE DIVISION USING TXN-RECORD
                         ACCT-RECORD
                         LS-GL-ENTRIES
                         LS-TXN-RESULT.
MAIN-LOGIC.
    PERFORM VALIDATE-AMOUNT
    PERFORM VALIDATE-DR-CR
    *> For reversals, swap the debit/credit direction before
    *> account status validation so legal-hold check uses
    *> the correct (swapped) DR/CR indicator
    IF TXN-TYPE = "REV"
        PERFORM SETUP-REVERSAL
    END-IF
    PERFORM VALIDATE-ACCOUNT-STATUS
    PERFORM CHECK-BALANCE
    PERFORM CHECK-CD-WITHDRAWAL
    PERFORM CAPTURE-BEFORE-SNAPSHOT
    PERFORM POST-TRANSACTION
    PERFORM UPDATE-AVAILABLE-BALANCE
    PERFORM CAPTURE-AFTER-SNAPSHOT
    PERFORM UPDATE-MTD-LOW-BAL
    PERFORM MAP-GL-ENTRIES
    PERFORM CHECK-CTR
    MOVE TXN-POST-DATE TO ACCT-LAST-TXN-DATE
    MOVE "E0000" TO LS-TXN-RESULT-CODE
    MOVE "Transaction posted successfully" TO LS-TXN-RESULT-MSG
    GOBACK.

*> ---------------------------------------------------------------
*> Validate transaction amount
*> ---------------------------------------------------------------
VALIDATE-AMOUNT.
    IF TXN-AMOUNT = ZERO
        MOVE "E0031" TO LS-TXN-RESULT-CODE
        MOVE "Transaction amount is zero" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    IF TXN-AMOUNT < ZERO
        MOVE "E0032" TO LS-TXN-RESULT-CODE
        MOVE "Transaction amount is negative" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF.

*> ---------------------------------------------------------------
*> Validate debit/credit indicator
*> ---------------------------------------------------------------
VALIDATE-DR-CR.
    IF TXN-DR-CR NOT = "D" AND TXN-DR-CR NOT = "C"
        MOVE "E0037" TO LS-TXN-RESULT-CODE
        MOVE "Invalid debit/credit indicator"
            TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF.

*> ---------------------------------------------------------------
*> Validate account status flags
*> NOTE: OFAC screening is enforced at two levels:
*>   1. CIF level - CIFMGMT checks OFAC status on the customer
*>      record and blocks all activity for flagged customers.
*>   2. Account level - An OFAC match results in the account
*>      being placed on legal hold (ACCT-LEGAL-HOLD = "Y"),
*>      which is checked below to block debit transactions.
*> ---------------------------------------------------------------
VALIDATE-ACCOUNT-STATUS.
    IF ACCT-STATUS = "F"
        MOVE "E0033" TO LS-TXN-RESULT-CODE
        MOVE "Account is frozen" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "C"
        MOVE "E0034" TO LS-TXN-RESULT-CODE
        MOVE "Account is closed" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-TXN-RESULT-CODE
        MOVE "Account is escheated" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    *> Legal hold check - also covers OFAC-flagged accounts
    IF ACCT-LEGAL-HOLD = "Y" AND TXN-DR-CR = "D"
        MOVE "E0035" TO LS-TXN-RESULT-CODE
        MOVE "Account has legal hold" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-TXN-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    *> Garnishment blocks all debits — court order freezes outflows
    IF ACCT-GARNISHMENT = "Y" AND TXN-DR-CR = "D"
        MOVE "E0045" TO LS-TXN-RESULT-CODE
        MOVE "Account under garnishment - debits blocked"
            TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    *> Dormant accounts may receive credits (deposits, interest)
    *> but debits require reactivation to prevent unauthorized outflows.
    IF ACCT-STATUS = "D" AND TXN-DR-CR = "D"
        MOVE "E0013" TO LS-TXN-RESULT-CODE
        MOVE "Account is dormant - debits not permitted"
            TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF
    *> Restricted accounts: debits blocked, credits allowed
    IF ACCT-STATUS = "R" AND TXN-DR-CR = "D"
        MOVE "E0043" TO LS-TXN-RESULT-CODE
        MOVE "Account is restricted - debits not permitted"
            TO LS-TXN-RESULT-MSG
        GOBACK
    END-IF.

*> ---------------------------------------------------------------
*> Set up reversal - swap debit/credit direction
*> A reversal of a credit (deposit) becomes a debit
*> A reversal of a debit (withdrawal) becomes a credit
*> ---------------------------------------------------------------
SETUP-REVERSAL.
    IF TXN-DR-CR = "C"
        MOVE "D" TO TXN-DR-CR
    ELSE
        MOVE "C" TO TXN-DR-CR
    END-IF.

*> ---------------------------------------------------------------
*> Check sufficient funds for withdrawals (debits)
*> ---------------------------------------------------------------
CHECK-BALANCE.
    IF TXN-DR-CR = "D"
        IF TXN-AMOUNT > ACCT-AVAIL-BAL
            MOVE "E0030" TO LS-TXN-RESULT-CODE
            MOVE "Insufficient funds" TO LS-TXN-RESULT-MSG
            GOBACK
        END-IF
    END-IF.

*> ---------------------------------------------------------------
*> Check if CD withdrawal is before maturity (early withdrawal)
*> If so, require explicit penalty acknowledgment from caller.
*> When acknowledged, compute penalty amount but allow withdrawal.
*> Penalty = ACCT-CD-EARLY-WD-PEN days of interest on balance.
*> ---------------------------------------------------------------
CHECK-CD-WITHDRAWAL.
    IF ACCT-SUB-TYPE = "CD" AND TXN-DR-CR = "D"
        IF ACCT-MATURITY-DATE > 0
            AND TXN-POST-DATE < ACCT-MATURITY-DATE
            *> Early withdrawal detected
            IF TXN-CD-EARLY-WD = "Y"
                *> Caller acknowledges penalty - compute penalty amount
                *> Penalty = (rate/100/365) * balance * penalty-days
                COMPUTE TXN-CD-PENALTY-AMT ROUNDED =
                    (ACCT-INT-RATE / 100 / 365)
                    * ACCT-LEDGER-BAL
                    * ACCT-CD-EARLY-WD-PEN
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-TXN-RESULT-CODE
                        MOVE "Overflow computing CD penalty"
                            TO LS-TXN-RESULT-MSG
                        GOBACK
                END-COMPUTE
            ELSE
                *> Early withdrawal not acknowledged - reject
                MOVE "E0039" TO LS-TXN-RESULT-CODE
                MOVE "CD early withdrawal requires penalty ack"
                    TO LS-TXN-RESULT-MSG
                GOBACK
            END-IF
        END-IF
    END-IF.

*> ---------------------------------------------------------------
*> Capture balance snapshots before posting
*> ---------------------------------------------------------------
CAPTURE-BEFORE-SNAPSHOT.
    MOVE ACCT-LEDGER-BAL TO TXN-BAL-BEFORE
    MOVE ACCT-AVAIL-BAL TO TXN-AVAIL-BEFORE.

*> ---------------------------------------------------------------
*> Post the transaction to ledger balance
*> ---------------------------------------------------------------
POST-TRANSACTION.
    IF TXN-DR-CR = "C"
        ADD TXN-AMOUNT TO ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-TXN-RESULT-CODE
                MOVE "Arithmetic overflow on deposit"
                    TO LS-TXN-RESULT-MSG
                GOBACK
        END-ADD
    ELSE
        SUBTRACT TXN-AMOUNT FROM ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-TXN-RESULT-CODE
                MOVE "Arithmetic overflow on withdrawal"
                    TO LS-TXN-RESULT-MSG
                GOBACK
        END-SUBTRACT
    END-IF.

*> ---------------------------------------------------------------
*> Update available balance = ledger - holds
*> ---------------------------------------------------------------
UPDATE-AVAILABLE-BALANCE.
    COMPUTE ACCT-AVAIL-BAL =
        ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
        ON SIZE ERROR
            *> Rollback ledger balance to pre-POST snapshot
            MOVE TXN-BAL-BEFORE TO ACCT-LEDGER-BAL
            MOVE "E0040" TO LS-TXN-RESULT-CODE
            MOVE "Arithmetic overflow on available balance"
                TO LS-TXN-RESULT-MSG
            GOBACK
    END-COMPUTE.

*> ---------------------------------------------------------------
*> Capture balance snapshots after posting
*> ---------------------------------------------------------------
CAPTURE-AFTER-SNAPSHOT.
    MOVE ACCT-LEDGER-BAL TO TXN-BAL-AFTER
    MOVE ACCT-AVAIL-BAL TO TXN-AVAIL-AFTER.

*> ---------------------------------------------------------------
*> Track month-to-date low balance watermark
*> Updates ACCT-MTD-LOW-BAL if the new ledger balance is the
*> lowest seen this month (reset monthly by EOMPROC0).
*> ---------------------------------------------------------------
UPDATE-MTD-LOW-BAL.
    IF ACCT-LEDGER-BAL < ACCT-MTD-LOW-BAL
        MOVE ACCT-LEDGER-BAL TO ACCT-MTD-LOW-BAL
    END-IF.

*> ---------------------------------------------------------------
*> Map GL entries based on transaction type and account sub-type
*> ---------------------------------------------------------------
MAP-GL-ENTRIES.
    PERFORM DETERMINE-DEPOSIT-GL
    EVALUATE TXN-TYPE
        WHEN "DEP"
            MOVE 0000001010 TO LS-GL-DR-ACCOUNT
            MOVE WS-DEPOSIT-GL TO LS-GL-CR-ACCOUNT
        WHEN "WDL"
            MOVE WS-DEPOSIT-GL TO LS-GL-DR-ACCOUNT
            MOVE 0000001010 TO LS-GL-CR-ACCOUNT
        WHEN "FEE"
            MOVE WS-DEPOSIT-GL TO LS-GL-DR-ACCOUNT
            MOVE 0000007500 TO LS-GL-CR-ACCOUNT
        WHEN "INT"
            MOVE 0000008010 TO LS-GL-DR-ACCOUNT
            MOVE WS-DEPOSIT-GL TO LS-GL-CR-ACCOUNT
        WHEN "REV"
            *> Reversal mirrors original GL but swapped direction
            *> DR/CR already swapped by SETUP-REVERSAL
            IF TXN-DR-CR = "D"
                *> Reversing a deposit: debit deposit-GL, credit cash
                MOVE WS-DEPOSIT-GL TO LS-GL-DR-ACCOUNT
                MOVE 0000001010 TO LS-GL-CR-ACCOUNT
            ELSE
                *> Reversing a withdrawal: debit cash, credit deposit-GL
                MOVE 0000001010 TO LS-GL-DR-ACCOUNT
                MOVE WS-DEPOSIT-GL TO LS-GL-CR-ACCOUNT
            END-IF
        WHEN OTHER
            *> Unknown type: route to suspense for manual review
            MOVE 0000009999 TO LS-GL-DR-ACCOUNT
            MOVE 0000009999 TO LS-GL-CR-ACCOUNT
    END-EVALUATE
    MOVE TXN-AMOUNT TO LS-GL-AMOUNT
    MOVE "Y" TO LS-GL-POST-FLAG.

*> ---------------------------------------------------------------
*> Determine the deposit GL account based on account sub-type
*> ---------------------------------------------------------------
DETERMINE-DEPOSIT-GL.
    EVALUATE ACCT-SUB-TYPE
        WHEN "CH"
            MOVE 0000004010 TO WS-DEPOSIT-GL
        WHEN "SV"
            MOVE 0000004030 TO WS-DEPOSIT-GL
        WHEN "MM"
            MOVE 0000004040 TO WS-DEPOSIT-GL
        WHEN "CD"
            MOVE 0000004050 TO WS-DEPOSIT-GL
        WHEN OTHER
            MOVE 0000009999 TO WS-DEPOSIT-GL
    END-EVALUATE.

*> ---------------------------------------------------------------
*> Check if cash amount triggers CTR reporting
*> ---------------------------------------------------------------
CHECK-CTR.
    IF TXN-CASH-AMOUNT > WS-CTR-THRESHOLD
        MOVE "Y" TO TXN-CTR-REPORTABLE
    ELSE
        MOVE "N" TO TXN-CTR-REPORTABLE
    END-IF.
