IDENTIFICATION DIVISION.
PROGRAM-ID. LOANPMT0.
*> ================================================================
*> LOANPMT0 - Loan Payment Processor
*> Processes loan payments, late checks, payoff calcs, status
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-INT-PORTION             PIC S9(13)V99.
01  WS-PRIN-PORTION            PIC S9(13)V99.
01  WS-REMAINING-INT           PIC S9(11)V9(6).
01  WS-PAYOFF-AMT              PIC S9(13)V99.
01  WS-ACCRUED-INT-2DP         PIC S9(13)V99.
01  WS-NEXT-PMT-YYYY           PIC 9(4).
01  WS-NEXT-PMT-MM             PIC 9(2).
01  WS-NEXT-PMT-DD             PIC 9(2).
01  WS-NEXT-PMT-WORK           PIC 9(8).
01  WS-DAYS-LATE               PIC 9(4).
01  WS-LEAP-YEAR-REM4          PIC 9(4).
01  WS-LEAP-YEAR-REM100        PIC 9(4).
01  WS-LEAP-YEAR-REM400        PIC 9(4).
01  WS-LATE-FEE-AMT            PIC S9(9)V99.
01  WS-LATE-FEE-PCT            PIC 9V99 VALUE 0.05.

LINKAGE SECTION.
01  LS-LOAN-FUNCTION           PIC X(4).
COPY CPYACCT.
01  LS-PAYMENT-AMT             PIC S9(13)V99.
01  LS-PAYMENT-DATE            PIC 9(8).
01  LS-LOAN-RESULT.
    05  LS-LOAN-RESULT-CODE    PIC X(5).
    05  LS-LOAN-RESULT-MSG     PIC X(50).
    05  LS-LOAN-INT-PORTION    PIC S9(13)V99.
    05  LS-LOAN-PRIN-PORTION   PIC S9(13)V99.
    05  LS-LOAN-NEW-BALANCE    PIC S9(13)V99.

PROCEDURE DIVISION USING LS-LOAN-FUNCTION
                         ACCT-RECORD
                         LS-PAYMENT-AMT
                         LS-PAYMENT-DATE
                         LS-LOAN-RESULT.
MAIN-LOGIC.
    INITIALIZE LS-LOAN-RESULT
    EVALUATE LS-LOAN-FUNCTION
        WHEN "PMNT"
            PERFORM PROCESS-PAYMENT
        WHEN "LATE"
            PERFORM CHECK-LATE
        WHEN "POFF"
            PERFORM CALC-PAYOFF
        WHEN "STAT"
            PERFORM GET-STATUS
        WHEN OTHER
            MOVE "E0001" TO LS-LOAN-RESULT-CODE
            MOVE "Invalid loan function" TO LS-LOAN-RESULT-MSG
    END-EVALUATE
    GOBACK.

*> ---------------------------------------------------------------
*> PMNT - Process a loan payment
*> ---------------------------------------------------------------
PROCESS-PAYMENT.
    *> Validate account type is loan
    IF ACCT-TYPE NOT = "L"
        MOVE "E0041" TO LS-LOAN-RESULT-CODE
        MOVE "Account is not a loan" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    *> Validate account is active
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-LOAN-RESULT-CODE
        MOVE "Account is closed" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-LOAN-RESULT-CODE
        MOVE "Account is escheated" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-LOAN-RESULT-CODE
        MOVE "Account is frozen" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-LOAN-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    *> Validate payment amount > 0
    IF LS-PAYMENT-AMT <= ZERO
        MOVE "E0032" TO LS-LOAN-RESULT-CODE
        MOVE "Payment amount must be positive"
            TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    *> Check if loan is already paid off
    IF ACCT-LEDGER-BAL = ZERO AND ACCT-ACCRUED-INT = ZERO
        MOVE "E0042" TO LS-LOAN-RESULT-CODE
        MOVE "Loan is paid off" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    *> Round accrued interest to 2 decimal places for splitting
    COMPUTE WS-ACCRUED-INT-2DP ROUNDED = ACCT-ACCRUED-INT
    END-COMPUTE
    *> Split payment into interest and principal
    IF LS-PAYMENT-AMT <= WS-ACCRUED-INT-2DP
        *> Entire payment goes to interest
        MOVE LS-PAYMENT-AMT TO WS-INT-PORTION
        MOVE ZERO TO WS-PRIN-PORTION
        *> Reduce accrued interest by payment
        SUBTRACT LS-PAYMENT-AMT FROM ACCT-ACCRUED-INT
            ON SIZE ERROR
                MOVE "E0040" TO LS-LOAN-RESULT-CODE
                MOVE "Arithmetic overflow on interest reduction"
                    TO LS-LOAN-RESULT-MSG
                GOBACK
        END-SUBTRACT
        *> Cap at zero — rounding 6dp to 2dp can overshoot
        IF ACCT-ACCRUED-INT < ZERO
            MOVE ZERO TO ACCT-ACCRUED-INT
        END-IF
    ELSE
        *> Pay all accrued interest first, rest to principal
        MOVE WS-ACCRUED-INT-2DP TO WS-INT-PORTION
        COMPUTE WS-PRIN-PORTION =
            LS-PAYMENT-AMT - WS-ACCRUED-INT-2DP
            ON SIZE ERROR
                MOVE "E0040" TO LS-LOAN-RESULT-CODE
                MOVE "Arithmetic overflow on principal calc"
                    TO LS-LOAN-RESULT-MSG
                GOBACK
        END-COMPUTE
        *> Clear accrued interest
        MOVE ZERO TO ACCT-ACCRUED-INT
        *> Cap principal portion at remaining balance
        IF WS-PRIN-PORTION > ACCT-LEDGER-BAL
            MOVE ACCT-LEDGER-BAL TO WS-PRIN-PORTION
        END-IF
        *> Reduce loan balance by principal portion
        SUBTRACT WS-PRIN-PORTION FROM ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-LOAN-RESULT-CODE
                MOVE "Arithmetic overflow on loan payment"
                    TO LS-LOAN-RESULT-MSG
                GOBACK
        END-SUBTRACT
    END-IF
    *> Update available balance for consistency
    COMPUTE ACCT-AVAIL-BAL =
        ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
        ON SIZE ERROR
            MOVE "E0040" TO LS-LOAN-RESULT-CODE
            MOVE "Overflow on available balance update"
                TO LS-LOAN-RESULT-MSG
            GOBACK
    END-COMPUTE
    *> Track MTD low balance after payment
    IF ACCT-LEDGER-BAL < ACCT-MTD-LOW-BAL
        MOVE ACCT-LEDGER-BAL TO ACCT-MTD-LOW-BAL
    END-IF
    *> Update past due status
    IF LS-PAYMENT-AMT >= ACCT-PAST-DUE-AMT
        MOVE ZERO TO ACCT-PAST-DUE-DAYS
        MOVE ZERO TO ACCT-PAST-DUE-AMT
    ELSE
        SUBTRACT LS-PAYMENT-AMT FROM ACCT-PAST-DUE-AMT
            ON SIZE ERROR
                MOVE "E0040" TO LS-LOAN-RESULT-CODE
                MOVE "Arithmetic overflow on past due reduction"
                    TO LS-LOAN-RESULT-MSG
                GOBACK
        END-SUBTRACT
    END-IF
    *> Update next payment date (add 1 month: +100 to YYYYMMDD)
    IF ACCT-NEXT-PMT-DATE > 0
        MOVE ACCT-NEXT-PMT-DATE TO WS-NEXT-PMT-WORK
        DIVIDE WS-NEXT-PMT-WORK BY 10000
            GIVING WS-NEXT-PMT-YYYY
            REMAINDER WS-NEXT-PMT-WORK
        DIVIDE WS-NEXT-PMT-WORK BY 100
            GIVING WS-NEXT-PMT-MM
            REMAINDER WS-NEXT-PMT-DD
        ADD 1 TO WS-NEXT-PMT-MM
        IF WS-NEXT-PMT-MM > 12
            MOVE 1 TO WS-NEXT-PMT-MM
            ADD 1 TO WS-NEXT-PMT-YYYY
        END-IF
        *> Cap day for shorter months to avoid invalid dates
        IF WS-NEXT-PMT-DD > 28
            EVALUATE WS-NEXT-PMT-MM
                WHEN 2
                    COMPUTE WS-LEAP-YEAR-REM4 =
                        FUNCTION MOD(WS-NEXT-PMT-YYYY 4)
                    COMPUTE WS-LEAP-YEAR-REM100 =
                        FUNCTION MOD(WS-NEXT-PMT-YYYY 100)
                    COMPUTE WS-LEAP-YEAR-REM400 =
                        FUNCTION MOD(WS-NEXT-PMT-YYYY 400)
                    IF WS-LEAP-YEAR-REM4 = 0
                        AND (WS-LEAP-YEAR-REM100 NOT = 0
                             OR WS-LEAP-YEAR-REM400 = 0)
                        MOVE 29 TO WS-NEXT-PMT-DD
                    ELSE
                        MOVE 28 TO WS-NEXT-PMT-DD
                    END-IF
                WHEN 4
                WHEN 6
                WHEN 9
                WHEN 11
                    IF WS-NEXT-PMT-DD > 30
                        MOVE 30 TO WS-NEXT-PMT-DD
                    END-IF
            END-EVALUATE
        END-IF
        COMPUTE ACCT-NEXT-PMT-DATE =
            WS-NEXT-PMT-YYYY * 10000
            + WS-NEXT-PMT-MM * 100
            + WS-NEXT-PMT-DD
            ON SIZE ERROR
                MOVE "E0040" TO LS-LOAN-RESULT-CODE
                MOVE "Arithmetic overflow on next payment date"
                    TO LS-LOAN-RESULT-MSG
                GOBACK
        END-COMPUTE
    END-IF
    *> Decrement remaining term
    IF ACCT-REMAINING-TERM > 0
        SUBTRACT 1 FROM ACCT-REMAINING-TERM
    END-IF
    *> Reset late fee flag only when past-due is fully cleared
    *> Partial payments must not reset — prevents double-charging
    IF ACCT-PAST-DUE-AMT = ZERO
        MOVE "N" TO ACCT-LATE-FEE-ASSESSED
    END-IF
    *> Update last transaction date for dormancy tracking
    MOVE LS-PAYMENT-DATE TO ACCT-LAST-TXN-DATE
    *> Set result
    MOVE WS-INT-PORTION TO LS-LOAN-INT-PORTION
    MOVE WS-PRIN-PORTION TO LS-LOAN-PRIN-PORTION
    MOVE ACCT-LEDGER-BAL TO LS-LOAN-NEW-BALANCE
    MOVE "E0000" TO LS-LOAN-RESULT-CODE
    MOVE "Loan payment processed successfully"
        TO LS-LOAN-RESULT-MSG.

*> ---------------------------------------------------------------
*> LATE - Check if payment is past due
*> ---------------------------------------------------------------
CHECK-LATE.
    IF ACCT-TYPE NOT = "L"
        MOVE "E0041" TO LS-LOAN-RESULT-CODE
        MOVE "Account is not a loan" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-LOAN-RESULT-CODE
        MOVE "Account is closed" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-LOAN-RESULT-CODE
        MOVE "Account is escheated" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-LOAN-RESULT-CODE
        MOVE "Account is frozen" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-LOAN-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-NEXT-PMT-DATE > 0
        AND LS-PAYMENT-DATE > ACCT-NEXT-PMT-DATE
        *> Payment is past due - compute actual days late
        COMPUTE WS-DAYS-LATE =
            FUNCTION INTEGER-OF-DATE(LS-PAYMENT-DATE)
          - FUNCTION INTEGER-OF-DATE(ACCT-NEXT-PMT-DATE)
        MOVE WS-DAYS-LATE TO ACCT-PAST-DUE-DAYS
        ADD ACCT-PAYMENT-AMT TO ACCT-PAST-DUE-AMT
            ON SIZE ERROR
                MOVE "E0040" TO LS-LOAN-RESULT-CODE
                MOVE "Overflow on past due accumulation"
                    TO LS-LOAN-RESULT-MSG
                GOBACK
        END-ADD
        *> Assess late fee if not already assessed this cycle
        IF ACCT-LATE-FEE-ASSESSED = "N"
            MOVE "Y" TO ACCT-LATE-FEE-ASSESSED
            *> Late fee = 5% of scheduled payment amount
            COMPUTE WS-LATE-FEE-AMT ROUNDED =
                ACCT-PAYMENT-AMT * WS-LATE-FEE-PCT
                ON SIZE ERROR
                    MOVE "E0040" TO LS-LOAN-RESULT-CODE
                    MOVE "Arithmetic overflow on late fee calc"
                        TO LS-LOAN-RESULT-MSG
                    GOBACK
            END-COMPUTE
            IF WS-LATE-FEE-AMT > ZERO
                ADD WS-LATE-FEE-AMT TO ACCT-PAST-DUE-AMT
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-LOAN-RESULT-CODE
                        MOVE "Overflow on late fee past due"
                            TO LS-LOAN-RESULT-MSG
                        GOBACK
                END-ADD
                ADD WS-LATE-FEE-AMT TO ACCT-YTD-FEES-CHARGED
                    ON SIZE ERROR
                        CONTINUE
                END-ADD
                MOVE WS-LATE-FEE-AMT TO LS-LOAN-INT-PORTION
            END-IF
        END-IF
    END-IF
    MOVE "E0000" TO LS-LOAN-RESULT-CODE
    MOVE "Late check completed" TO LS-LOAN-RESULT-MSG.

*> ---------------------------------------------------------------
*> POFF - Calculate payoff amount
*> ---------------------------------------------------------------
CALC-PAYOFF.
    IF ACCT-TYPE NOT = "L"
        MOVE "E0041" TO LS-LOAN-RESULT-CODE
        MOVE "Account is not a loan" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-LOAN-RESULT-CODE
        MOVE "Account is closed" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-LOAN-RESULT-CODE
        MOVE "Account is escheated" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-LOAN-RESULT-CODE
        MOVE "Account is frozen" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-LOAN-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    COMPUTE WS-ACCRUED-INT-2DP ROUNDED = ACCT-ACCRUED-INT
    END-COMPUTE
    *> Payoff = principal + accrued interest + past-due amounts
    *> - escrow surplus (escrow balance returned to borrower)
    COMPUTE WS-PAYOFF-AMT =
        ACCT-LEDGER-BAL + WS-ACCRUED-INT-2DP
        + ACCT-PAST-DUE-AMT - ACCT-ESCROW-BAL
        ON SIZE ERROR
            MOVE "E0040" TO LS-LOAN-RESULT-CODE
            MOVE "Arithmetic overflow on payoff calc"
                TO LS-LOAN-RESULT-MSG
            GOBACK
    END-COMPUTE
    *> Floor payoff at zero (escrow surplus can't create negative payoff)
    IF WS-PAYOFF-AMT < ZERO
        MOVE ZERO TO WS-PAYOFF-AMT
    END-IF
    MOVE WS-PAYOFF-AMT TO LS-LOAN-NEW-BALANCE
    MOVE "E0000" TO LS-LOAN-RESULT-CODE
    MOVE "Payoff amount calculated" TO LS-LOAN-RESULT-MSG.

*> ---------------------------------------------------------------
*> STAT - Return loan status summary
*> ---------------------------------------------------------------
GET-STATUS.
    IF ACCT-TYPE NOT = "L"
        MOVE "E0041" TO LS-LOAN-RESULT-CODE
        MOVE "Account is not a loan" TO LS-LOAN-RESULT-MSG
        GOBACK
    END-IF
    MOVE ACCT-LEDGER-BAL TO LS-LOAN-NEW-BALANCE
    MOVE "E0000" TO LS-LOAN-RESULT-CODE
    MOVE "Loan status retrieved" TO LS-LOAN-RESULT-MSG.
