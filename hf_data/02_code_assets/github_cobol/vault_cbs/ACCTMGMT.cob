IDENTIFICATION DIVISION.
PROGRAM-ID. ACCTMGMT.
*> ================================================================
*> ACCTMGMT - Account Management
*> OPEN = Open account, CLOS = Close account,
*> VALD = Validate, CHKD = Check digit (Luhn)
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-CURRENT-DATE-DATA.
    05  WS-CURRENT-DATE        PIC 9(8).
    05  WS-CURRENT-TIME        PIC 9(6).
    05  FILLER                 PIC X(7).

*> Luhn working fields
01  WS-ACCT-NUM-STR           PIC X(12).
01  WS-DIGIT                  PIC 9(1).
01  WS-DOUBLED                PIC 9(2).
01  WS-LUHN-SUM               PIC 9(5) VALUE 0.
01  WS-LUHN-RESULT            PIC 9(1).
01  WS-POS                    PIC 9(2).
01  WS-IDX                    PIC 9(2).

LINKAGE SECTION.
01  LS-FUNCTION                   PIC X(4).
COPY CPYACCT.
COPY CPYCIF.
01  LS-ACCT-RESULT.
    05  LS-ACCT-RESULT-CODE       PIC X(5).
    05  LS-ACCT-RESULT-MSG        PIC X(50).

PROCEDURE DIVISION USING LS-FUNCTION
                         ACCT-RECORD
                         CIF-RECORD
                         LS-ACCT-RESULT.
    EVALUATE LS-FUNCTION
        WHEN "OPEN"
            PERFORM OPEN-ACCOUNT
        WHEN "CLOS"
            PERFORM CLOSE-ACCOUNT
        WHEN "CHKD"
            PERFORM CHECK-DIGIT
        WHEN OTHER
            MOVE "E0001" TO LS-ACCT-RESULT-CODE
            MOVE "Invalid function code" TO LS-ACCT-RESULT-MSG
    END-EVALUATE
    GOBACK.

*> ---------------------------------------------------------------
*> OPEN-ACCOUNT - Open a new account
*> ---------------------------------------------------------------
OPEN-ACCOUNT.
    IF CIF-CIP-VERIFIED NOT = "Y"
        MOVE "E0021" TO LS-ACCT-RESULT-CODE
        MOVE "CIF not CIP verified" TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    PERFORM VALIDATE-PRODUCT-CODE
    IF LS-ACCT-RESULT-CODE NOT = "E0000"
        EXIT PARAGRAPH
    END-IF

    MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-DATA

    MOVE "A" TO ACCT-STATUS
    MOVE WS-CURRENT-DATE TO ACCT-OPEN-DATE
    MOVE WS-CURRENT-DATE TO ACCT-CREATED-DATE
    MOVE "SYSTEM" TO ACCT-CREATED-USER

    MOVE 0 TO ACCT-LEDGER-BAL
    MOVE 0 TO ACCT-AVAIL-BAL
    MOVE 0 TO ACCT-COLLECTED-BAL
    MOVE 0 TO ACCT-HOLD-AMOUNT
    MOVE 0 TO ACCT-PENDING-DR
    MOVE 0 TO ACCT-PENDING-CR
    MOVE 0 TO ACCT-ACCRUED-INT
    MOVE 0 TO ACCT-YTD-INT-EARNED
    MOVE 0 TO ACCT-YTD-INT-PAID
    MOVE 0 TO ACCT-PTD-INT-EARNED
    MOVE 0 TO ACCT-MTD-AVG-BAL
    MOVE 0 TO ACCT-MTD-LOW-BAL

    *> Overdraft fields - Reg E requires explicit opt-in
    MOVE "N" TO ACCT-OD-OPTED-IN
    MOVE "N" TO ACCT-OD-PROTECTION
    MOVE 0 TO ACCT-OD-LIMIT
    MOVE 0 TO ACCT-NSF-COUNT-MTD
    MOVE 0 TO ACCT-NSF-COUNT-TODAY
    MOVE 0 TO ACCT-NSF-COUNT-YTD

    *> Status flags
    MOVE "N" TO ACCT-LEGAL-HOLD
    MOVE "N" TO ACCT-GARNISHMENT
    MOVE "N" TO ACCT-DECEASED
    MOVE 0 TO ACCT-STOP-PAYS-ACTIVE
    MOVE "N" TO ACCT-LATE-FEE-ASSESSED

    *> Date fields (prevent garbage affecting dormancy detection)
    MOVE 0 TO ACCT-CLOSE-DATE
    MOVE 0 TO ACCT-MATURITY-DATE
    MOVE 0 TO ACCT-LAST-TXN-DATE
    MOVE 0 TO ACCT-LAST-STMT-DATE
    MOVE 0 TO ACCT-NEXT-STMT-DATE
    MOVE 0 TO ACCT-STMT-CYCLE
    MOVE 0 TO ACCT-HOLD-RELEASE-DT

    *> Fee tracking (prevent corrupted YTD totals)
    MOVE 0 TO ACCT-MONTHLY-FEE
    MOVE "NW" TO ACCT-FEE-WAIVER-CODE
    MOVE 0 TO ACCT-FEE-WAIVER-AMT
    MOVE 0 TO ACCT-YTD-FEES-CHARGED
    MOVE 0 TO ACCT-YTD-FEES-WAIVED

    *> Reg D transfer counter
    MOVE 0 TO ACCT-OL-TXN-COUNT-MTD

    *> Interest parameters (prevent garbage rate/basis)
    MOVE 0 TO ACCT-INT-RATE
    MOVE SPACES TO ACCT-INT-RATE-TYPE
    MOVE SPACES TO ACCT-INT-INDEX-CODE
    MOVE 0 TO ACCT-INT-INDEX-MARGIN
    MOVE SPACES TO ACCT-INT-CALC-METHOD
    MOVE SPACES TO ACCT-INT-ACCRUAL-BASIS
    MOVE SPACES TO ACCT-INT-COMPOUND-FREQ
    MOVE SPACES TO ACCT-INT-PAY-FREQ
    MOVE 0 TO ACCT-INT-NEXT-PAY-DATE

    *> Loan-specific fields (prevent stale data in reused records)
    MOVE 0 TO ACCT-ORIGINAL-AMT
    MOVE 0 TO ACCT-PAYMENT-AMT
    MOVE SPACES TO ACCT-PAYMENT-FREQ
    MOVE 0 TO ACCT-NEXT-PMT-DATE
    MOVE 0 TO ACCT-REMAINING-TERM
    MOVE 0 TO ACCT-ORIGINAL-TERM
    MOVE 0 TO ACCT-PAST-DUE-DAYS
    MOVE 0 TO ACCT-PAST-DUE-AMT
    MOVE 0 TO ACCT-ESCROW-BAL
    MOVE SPACES TO ACCT-COLLATERAL-CODE

    *> CD-specific fields
    MOVE 0 TO ACCT-CD-TERM-MONTHS
    MOVE SPACES TO ACCT-CD-RENEWAL-TYPE
    MOVE 0 TO ACCT-CD-EARLY-WD-PEN
    MOVE 0 TO ACCT-CD-GRACE-DAYS

    MOVE "E0000" TO LS-ACCT-RESULT-CODE
    MOVE "Account opened successfully" TO LS-ACCT-RESULT-MSG.

*> ---------------------------------------------------------------
*> CLOSE-ACCOUNT - Close an existing account
*> ---------------------------------------------------------------
CLOSE-ACCOUNT.
    IF ACCT-STATUS NOT = "A" AND ACCT-STATUS NOT = "D"
        MOVE "E0011" TO LS-ACCT-RESULT-CODE
        MOVE "Only active accounts can be closed"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-LEGAL-HOLD = "Y"
        MOVE "E0035" TO LS-ACCT-RESULT-CODE
        MOVE "Cannot close account under legal hold"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-GARNISHMENT = "Y"
        MOVE "E0045" TO LS-ACCT-RESULT-CODE
        MOVE "Cannot close account under garnishment"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-LEDGER-BAL NOT = 0
        MOVE "E0016" TO LS-ACCT-RESULT-CODE
        MOVE "Account has balance" TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-ACCRUED-INT NOT = 0
        MOVE "E0047" TO LS-ACCT-RESULT-CODE
        MOVE "Account has unposted accrued interest"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-HOLD-AMOUNT NOT = 0
        MOVE "E0017" TO LS-ACCT-RESULT-CODE
        MOVE "Account has active holds" TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-PENDING-DR NOT = 0 OR ACCT-PENDING-CR NOT = 0
        MOVE "E0017" TO LS-ACCT-RESULT-CODE
        MOVE "Account has pending transactions"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-PAST-DUE-AMT NOT = 0
        MOVE "E0048" TO LS-ACCT-RESULT-CODE
        MOVE "Account has past-due amount"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    IF ACCT-ESCROW-BAL NOT = 0
        MOVE "E0049" TO LS-ACCT-RESULT-CODE
        MOVE "Account has escrow balance"
            TO LS-ACCT-RESULT-MSG
        EXIT PARAGRAPH
    END-IF

    MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-DATA

    MOVE "C" TO ACCT-STATUS
    MOVE WS-CURRENT-DATE TO ACCT-CLOSE-DATE

    MOVE "E0000" TO LS-ACCT-RESULT-CODE
    MOVE "Account closed successfully" TO LS-ACCT-RESULT-MSG.

*> ---------------------------------------------------------------
*> VALIDATE-PRODUCT-CODE - Validate product code and set
*> account type/sub-type defaults based on product
*> ---------------------------------------------------------------
VALIDATE-PRODUCT-CODE.
    EVALUATE ACCT-PRODUCT-CODE
        WHEN "DDA1"
            MOVE "D" TO ACCT-TYPE
            MOVE "CH" TO ACCT-SUB-TYPE
        WHEN "DDA2"
            MOVE "D" TO ACCT-TYPE
            MOVE "CH" TO ACCT-SUB-TYPE
        WHEN "SAV1"
            MOVE "D" TO ACCT-TYPE
            MOVE "SV" TO ACCT-SUB-TYPE
        WHEN "MMA1"
            MOVE "D" TO ACCT-TYPE
            MOVE "MM" TO ACCT-SUB-TYPE
        WHEN OTHER
            *> Check if it starts with "CD" for CD terms
            IF ACCT-PRODUCT-CODE(1:2) = "CD"
                MOVE "D" TO ACCT-TYPE
                MOVE "CD" TO ACCT-SUB-TYPE
            ELSE
                MOVE "E0018" TO LS-ACCT-RESULT-CODE
                MOVE "Invalid product code"
                    TO LS-ACCT-RESULT-MSG
                EXIT PARAGRAPH
            END-IF
    END-EVALUATE
    MOVE "E0000" TO LS-ACCT-RESULT-CODE.

*> ---------------------------------------------------------------
*> CHECK-DIGIT - Luhn check digit calculation/validation
*> ---------------------------------------------------------------
CHECK-DIGIT.
    PERFORM CALC-LUHN-DIGIT

    IF ACCT-CHECK-DIGIT = 0
        MOVE WS-LUHN-RESULT TO ACCT-CHECK-DIGIT
        MOVE "E0000" TO LS-ACCT-RESULT-CODE
        MOVE "Check digit calculated" TO LS-ACCT-RESULT-MSG
    ELSE
        IF ACCT-CHECK-DIGIT = WS-LUHN-RESULT
            MOVE "E0000" TO LS-ACCT-RESULT-CODE
            MOVE "Check digit valid" TO LS-ACCT-RESULT-MSG
        ELSE
            MOVE "E0019" TO LS-ACCT-RESULT-CODE
            MOVE "Check digit mismatch" TO LS-ACCT-RESULT-MSG
        END-IF
    END-IF.

*> ---------------------------------------------------------------
*> CALC-LUHN-DIGIT - Calculate Luhn check digit for ACCT-NUMBER
*> Doubles odd positions from right (pos 1, 3, 5, ...)
*> ---------------------------------------------------------------
CALC-LUHN-DIGIT.
    MOVE ACCT-NUMBER TO WS-ACCT-NUM-STR
    MOVE 0 TO WS-LUHN-SUM

    PERFORM VARYING WS-POS FROM 1 BY 1
        UNTIL WS-POS > 12

        *> WS-IDX is the index into the string (left-to-right)
        *> corresponding to right-to-left position WS-POS
        COMPUTE WS-IDX = 13 - WS-POS

        MOVE WS-ACCT-NUM-STR(WS-IDX:1) TO WS-DIGIT

        *> Odd positions from right get doubled
        COMPUTE WS-DOUBLED =
            FUNCTION MOD(WS-POS, 2)
        IF WS-DOUBLED = 1
            COMPUTE WS-DOUBLED = WS-DIGIT * 2
            IF WS-DOUBLED > 9
                SUBTRACT 9 FROM WS-DOUBLED
            END-IF
            ADD WS-DOUBLED TO WS-LUHN-SUM
        ELSE
            ADD WS-DIGIT TO WS-LUHN-SUM
        END-IF
    END-PERFORM

    COMPUTE WS-LUHN-RESULT =
        FUNCTION MOD(10 - FUNCTION MOD(WS-LUHN-SUM, 10), 10).
