IDENTIFICATION DIVISION.
PROGRAM-ID. BSACTRO.
*> ================================================================
*> BSACTRO - BSA/AML Currency Transaction Report Generator
*> AGGR = Aggregate, CHEK = Check threshold,
*> STRC = Structuring detection, SARQ = SAR query
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
COPY CPYCONST.
01  WS-COMBINED-CASH           PIC S9(13)V99.
01  WS-TOTAL-TXN-COUNT        PIC 9(5).

LINKAGE SECTION.
01  LS-FUNCTION                   PIC X(4).
COPY CPYCTR.
01  LS-TXN-INFO.
    05  LS-BSA-CUST-ID           PIC 9(10).
    05  LS-BSA-TXN-DATE          PIC 9(8).
    05  LS-BSA-CASH-AMOUNT       PIC S9(13)V99.
    05  LS-BSA-CASH-DIRECTION    PIC X(1).
    *> I = Cash-in, O = Cash-out
    05  LS-BSA-IS-CASH           PIC X(1).
    05  LS-BSA-ACCT-NUMBER       PIC 9(12).
01  LS-BSA-RESULT.
    05  LS-BSA-RESULT-CODE        PIC X(5).
    05  LS-BSA-RESULT-MSG         PIC X(50).
    05  LS-BSA-CTR-REQUIRED       PIC X(1).
    05  LS-BSA-CASH-IN-TOTAL      PIC S9(13)V99.
    05  LS-BSA-CASH-OUT-TOTAL     PIC S9(13)V99.

PROCEDURE DIVISION USING LS-FUNCTION
                         CTR-RECORD
                         LS-TXN-INFO
                         LS-BSA-RESULT.
    EVALUATE LS-FUNCTION
        WHEN "CHEK"
            PERFORM DO-CHEK
        WHEN "AGGR"
            PERFORM DO-AGGR
        WHEN "STRC"
            PERFORM DO-STRC
        WHEN "SARQ"
            PERFORM DO-SARQ
        WHEN OTHER
            MOVE "E0001" TO LS-BSA-RESULT-CODE
            MOVE "Invalid function" TO LS-BSA-RESULT-MSG
            MOVE "N" TO LS-BSA-CTR-REQUIRED
    END-EVALUATE
    GOBACK.

*> ---------------------------------------------------------------
*> CHEK - Check single transaction against CTR threshold
*> ---------------------------------------------------------------
DO-CHEK.
    MOVE "E0000" TO LS-BSA-RESULT-CODE
    MOVE SPACES TO LS-BSA-RESULT-MSG
    MOVE "N" TO LS-BSA-CTR-REQUIRED
    MOVE ZEROS TO LS-BSA-CASH-IN-TOTAL
    MOVE ZEROS TO LS-BSA-CASH-OUT-TOTAL

    IF CTR-EXEMPT-FLAG = "Y"
        MOVE "Customer exempt from CTR" TO LS-BSA-RESULT-MSG
        GOBACK
    END-IF

    IF LS-BSA-IS-CASH = "N"
        MOVE "Non-cash transaction" TO LS-BSA-RESULT-MSG
        GOBACK
    END-IF

    IF LS-BSA-CASH-AMOUNT > WS-CTR-THRESHOLD
        MOVE "Y" TO LS-BSA-CTR-REQUIRED
        MOVE "CTR required" TO LS-BSA-RESULT-MSG
    END-IF
    *> Also check aggregated CTR-RECORD totals
    IF CTR-CASH-IN-TOTAL > WS-CTR-THRESHOLD
        MOVE "Y" TO LS-BSA-CTR-REQUIRED
        MOVE "CTR required - aggregate" TO LS-BSA-RESULT-MSG
    END-IF
    IF CTR-CASH-OUT-TOTAL > WS-CTR-THRESHOLD
        MOVE "Y" TO LS-BSA-CTR-REQUIRED
        MOVE "CTR required - aggregate" TO LS-BSA-RESULT-MSG
    END-IF
    IF LS-BSA-CTR-REQUIRED = "N"
        MOVE "CTR not required" TO LS-BSA-RESULT-MSG
    END-IF.

*> ---------------------------------------------------------------
*> AGGR - Aggregate cash per customer per day
*> ---------------------------------------------------------------
DO-AGGR.
    MOVE "E0000" TO LS-BSA-RESULT-CODE
    MOVE SPACES TO LS-BSA-RESULT-MSG
    MOVE "N" TO LS-BSA-CTR-REQUIRED

    *> GAP-02: Customer/date guard on CTR record
    IF CTR-CUST-ID = 0
        *> First aggregation - stamp customer ID and date
        MOVE LS-BSA-CUST-ID TO CTR-CUST-ID
        MOVE LS-BSA-TXN-DATE TO CTR-TXN-DATE
    ELSE
        *> Subsequent aggregation - validate customer/date match
        IF CTR-CUST-ID NOT = LS-BSA-CUST-ID
            OR CTR-TXN-DATE NOT = LS-BSA-TXN-DATE
            MOVE "E0002" TO LS-BSA-RESULT-CODE
            MOVE "Customer/date mismatch on CTR record"
                TO LS-BSA-RESULT-MSG
            GOBACK
        END-IF
    END-IF

    IF LS-BSA-IS-CASH = "Y"
        EVALUATE LS-BSA-CASH-DIRECTION
            WHEN "I"
                ADD LS-BSA-CASH-AMOUNT TO CTR-CASH-IN-TOTAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-BSA-RESULT-CODE
                        MOVE "Arithmetic overflow on cash-in"
                            TO LS-BSA-RESULT-MSG
                        GOBACK
                END-ADD
                ADD 1 TO CTR-CASH-IN-COUNT
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-BSA-RESULT-CODE
                        MOVE "Arithmetic overflow on cash-in count"
                            TO LS-BSA-RESULT-MSG
                        GOBACK
                END-ADD
            WHEN "O"
                ADD LS-BSA-CASH-AMOUNT TO CTR-CASH-OUT-TOTAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-BSA-RESULT-CODE
                        MOVE "Arithmetic overflow on cash-out"
                            TO LS-BSA-RESULT-MSG
                        GOBACK
                END-ADD
                ADD 1 TO CTR-CASH-OUT-COUNT
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-BSA-RESULT-CODE
                        MOVE "Arithmetic overflow on cash-out count"
                            TO LS-BSA-RESULT-MSG
                        GOBACK
                END-ADD
            WHEN OTHER
                MOVE "E0089" TO LS-BSA-RESULT-CODE
                MOVE "Invalid cash direction (must be I or O)"
                    TO LS-BSA-RESULT-MSG
                GOBACK
        END-EVALUATE
    END-IF

    MOVE CTR-CASH-IN-TOTAL TO LS-BSA-CASH-IN-TOTAL
    MOVE CTR-CASH-OUT-TOTAL TO LS-BSA-CASH-OUT-TOTAL

    IF CTR-EXEMPT-FLAG = "Y"
        MOVE "Customer exempt from CTR" TO LS-BSA-RESULT-MSG
        GOBACK
    END-IF

    *> 31 CFR 1010.311: CTR required for cash "in excess of"
    *> $10,000 — strictly greater than, not equal.
    EVALUATE TRUE
        WHEN CTR-CASH-IN-TOTAL > WS-CTR-THRESHOLD
            MOVE "Y" TO LS-BSA-CTR-REQUIRED
            MOVE "CTR required - cash in threshold"
                TO LS-BSA-RESULT-MSG
        WHEN CTR-CASH-OUT-TOTAL > WS-CTR-THRESHOLD
            MOVE "Y" TO LS-BSA-CTR-REQUIRED
            MOVE "CTR required - cash out threshold"
                TO LS-BSA-RESULT-MSG
        WHEN OTHER
            MOVE "CTR not required" TO LS-BSA-RESULT-MSG
    END-EVALUATE.

*> ---------------------------------------------------------------
*> STRC - Structuring detection
*> Flags when daily cash total is $8,000-$9,999 (just below CTR)
*> and there are multiple transactions (classic structuring)
*> ---------------------------------------------------------------
DO-STRC.
    MOVE "E0000" TO LS-BSA-RESULT-CODE
    MOVE SPACES TO LS-BSA-RESULT-MSG
    MOVE "N" TO LS-BSA-CTR-REQUIRED

    *> Combine cash-in and cash-out for structuring check
    COMPUTE WS-COMBINED-CASH =
        CTR-CASH-IN-TOTAL + CTR-CASH-OUT-TOTAL
        ON SIZE ERROR
            MOVE "E0040" TO LS-BSA-RESULT-CODE
            MOVE "Arithmetic overflow on combined cash"
                TO LS-BSA-RESULT-MSG
            GOBACK
    END-COMPUTE

    MOVE CTR-CASH-IN-TOTAL TO LS-BSA-CASH-IN-TOTAL
    MOVE CTR-CASH-OUT-TOTAL TO LS-BSA-CASH-OUT-TOTAL

    COMPUTE WS-TOTAL-TXN-COUNT =
        CTR-CASH-IN-COUNT + CTR-CASH-OUT-COUNT
        ON SIZE ERROR
            MOVE "E0040" TO LS-BSA-RESULT-CODE
            MOVE "Arithmetic overflow on txn count"
                TO LS-BSA-RESULT-MSG
            GOBACK
    END-COMPUTE

    *> Check if total falls in structuring range ($8K-$9,999.99)
    *> and there are multiple transactions (count > 1)
    IF WS-COMBINED-CASH >= WS-SAR-STRUCT-THRESHOLD
        AND WS-COMBINED-CASH <= WS-SAR-STRUCT-CEILING
        AND WS-TOTAL-TXN-COUNT > 1
        MOVE "E0082" TO LS-BSA-RESULT-CODE
        MOVE "SAR required - structuring detected"
            TO LS-BSA-RESULT-MSG
        MOVE "Y" TO LS-BSA-CTR-REQUIRED
    ELSE
        MOVE "No structuring pattern detected"
            TO LS-BSA-RESULT-MSG
    END-IF.

*> ---------------------------------------------------------------
*> SARQ - SAR query: check if customer has pending SAR flags
*> Uses CTR-RECORD filing status to determine pending SARs
*> ---------------------------------------------------------------
DO-SARQ.
    MOVE "E0000" TO LS-BSA-RESULT-CODE
    MOVE SPACES TO LS-BSA-RESULT-MSG
    MOVE "N" TO LS-BSA-CTR-REQUIRED
    MOVE CTR-CASH-IN-TOTAL TO LS-BSA-CASH-IN-TOTAL
    MOVE CTR-CASH-OUT-TOTAL TO LS-BSA-CASH-OUT-TOTAL

    IF CTR-FILING-STATUS = "P"
        MOVE "Y" TO LS-BSA-CTR-REQUIRED
        MOVE "Pending SAR exists for customer"
            TO LS-BSA-RESULT-MSG
    ELSE
        MOVE "No pending SAR for customer"
            TO LS-BSA-RESULT-MSG
    END-IF.
