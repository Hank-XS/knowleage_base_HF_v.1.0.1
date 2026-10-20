IDENTIFICATION DIVISION.
PROGRAM-ID. WIREXFR0.
*> ================================================================
*> WIREXFR0 - Wire Transfer Processor
*> SEND = Initiate outgoing, RECV = Process incoming,
*> COMP = Confirm settlement (PR->CP), RVRS = Reverse,
*> INQY = Inquiry
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-CURRENT-DATE           PIC 9(8).
01  WS-DUAL-CONTROL-THRESHOLD PIC S9(13)V99 VALUE +50000.00.
01  WS-SAVE-LEDGER-BAL        PIC S9(13)V99.

*> OFAC screening areas
COPY CPYOFAC.
01  WS-OFAC-FUNCTION          PIC X(4).
01  WS-OFAC-RESULT.
    05  WS-OFAC-RESULT-CODE   PIC X(5).
    05  WS-OFAC-RESULT-MSG    PIC X(50).

LINKAGE SECTION.
01  LS-WIRE-FUNCTION           PIC X(4).
COPY CPYWIRE.
COPY CPYACCT.
01  LS-WIRE-RESULT.
    05  LS-WIRE-RESULT-CODE    PIC X(5).
    05  LS-WIRE-RESULT-MSG     PIC X(50).

PROCEDURE DIVISION USING LS-WIRE-FUNCTION
                         WIRE-RECORD
                         ACCT-RECORD
                         LS-WIRE-RESULT.
MAIN-LOGIC.
    MOVE "E0000" TO LS-WIRE-RESULT-CODE
    MOVE SPACES TO LS-WIRE-RESULT-MSG

    EVALUATE LS-WIRE-FUNCTION
        WHEN "SEND"
            PERFORM PROCESS-SEND
        WHEN "RECV"
            PERFORM PROCESS-RECV
        WHEN "COMP"
            PERFORM PROCESS-COMPLETE
        WHEN "RVRS"
            PERFORM PROCESS-REVERSE
        WHEN "INQY"
            PERFORM PROCESS-INQUIRY
        WHEN OTHER
            MOVE "E0001" TO LS-WIRE-RESULT-CODE
            MOVE "Invalid wire function" TO LS-WIRE-RESULT-MSG
    END-EVALUATE
    GOBACK.

*> ---------------------------------------------------------------
*> PROCESS-SEND - Initiate an outgoing wire transfer
*> ---------------------------------------------------------------
PROCESS-SEND.
    *> Validate amount > 0
    IF WIRE-AMOUNT <= ZERO
        MOVE "E0002" TO LS-WIRE-RESULT-CODE
        MOVE "Wire amount must be positive" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Validate account is active (not closed or frozen)
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-WIRE-RESULT-CODE
        MOVE "Account is closed" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-WIRE-RESULT-CODE
        MOVE "Account is frozen" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-WIRE-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-WIRE-RESULT-CODE
        MOVE "Account is escheated" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-LEGAL-HOLD = "Y"
        MOVE "E0035" TO LS-WIRE-RESULT-CODE
        MOVE "Account has legal hold" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-GARNISHMENT = "Y"
        MOVE "E0045" TO LS-WIRE-RESULT-CODE
        MOVE "Account under garnishment - wires blocked"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "D"
        MOVE "E0013" TO LS-WIRE-RESULT-CODE
        MOVE "Account is dormant - wires not permitted"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "R"
        MOVE "E0043" TO LS-WIRE-RESULT-CODE
        MOVE "Account is restricted - wires not permitted"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Validate sufficient funds
    IF WIRE-AMOUNT > ACCT-AVAIL-BAL
        MOVE "E0097" TO LS-WIRE-RESULT-CODE
        MOVE "Wire: insufficient funds" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> OFAC beneficiary screening (P1 regulatory requirement)
    INITIALIZE OFAC-CHECK-RECORD
    INITIALIZE WS-OFAC-RESULT
    MOVE WIRE-BENE-NAME TO OFAC-CHECK-NAME
    MOVE WIRE-BENE-COUNTRY TO OFAC-CHECK-COUNTRY
    MOVE "B" TO OFAC-CHECK-TYPE
    MOVE "CHKB" TO WS-OFAC-FUNCTION
    CALL "OFACCHK0" USING WS-OFAC-FUNCTION
                          OFAC-CHECK-RECORD
                          WS-OFAC-RESULT
    IF WS-OFAC-RESULT-CODE = "E0025"
        MOVE "E0025" TO LS-WIRE-RESULT-CODE
        MOVE "OFAC match on beneficiary"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Dual control: amounts >= 50000 require approval
    IF WIRE-AMOUNT >= WS-DUAL-CONTROL-THRESHOLD
        IF WIRE-APPROVED-BY = SPACES
            MOVE "E0098" TO LS-WIRE-RESULT-CODE
            MOVE "Wire: approval required for amount >= 50000"
                TO LS-WIRE-RESULT-MSG
            GOBACK
        END-IF
        IF WIRE-APPROVED-BY = WIRE-CREATED-BY
            MOVE "E0098" TO LS-WIRE-RESULT-CODE
            MOVE "Wire approver must differ from creator"
                TO LS-WIRE-RESULT-MSG
            GOBACK
        END-IF
    END-IF

    *> Debit account
    MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
    SUBTRACT WIRE-AMOUNT FROM ACCT-LEDGER-BAL
        ON SIZE ERROR
            MOVE "E0040" TO LS-WIRE-RESULT-CODE
            MOVE "Arithmetic overflow on wire send"
                TO LS-WIRE-RESULT-MSG
            GOBACK
    END-SUBTRACT
    COMPUTE ACCT-AVAIL-BAL =
        ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
        ON SIZE ERROR
            MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
            MOVE "E0040" TO LS-WIRE-RESULT-CODE
            MOVE "Arithmetic overflow on wire send"
                TO LS-WIRE-RESULT-MSG
            GOBACK
    END-COMPUTE

    *> Track MTD low balance after wire debit
    IF ACCT-LEDGER-BAL < ACCT-MTD-LOW-BAL
        MOVE ACCT-LEDGER-BAL TO ACCT-MTD-LOW-BAL
    END-IF

    *> Set wire status and date
    MOVE "PR" TO WIRE-STATUS
    MOVE FUNCTION CURRENT-DATE(1:8) TO WIRE-SEND-DATE
    MOVE FUNCTION CURRENT-DATE(1:8) TO WIRE-VALUE-DATE
    MOVE "O" TO WIRE-TYPE

    MOVE FUNCTION CURRENT-DATE(1:8) TO ACCT-LAST-TXN-DATE
    MOVE "E0000" TO LS-WIRE-RESULT-CODE
    MOVE "Wire transfer initiated" TO LS-WIRE-RESULT-MSG.

*> ---------------------------------------------------------------
*> PROCESS-RECV - Process an incoming wire transfer
*> ---------------------------------------------------------------
PROCESS-RECV.
    *> Validate amount > 0
    IF WIRE-AMOUNT <= ZERO
        MOVE "E0002" TO LS-WIRE-RESULT-CODE
        MOVE "Wire amount must be positive" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Validate account is active (not closed or frozen)
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-WIRE-RESULT-CODE
        MOVE "Account is closed" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-WIRE-RESULT-CODE
        MOVE "Account is frozen" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-WIRE-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-WIRE-RESULT-CODE
        MOVE "Account is escheated" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    *> Legal hold does NOT block incoming credits (only debits)

    *> OFAC originator screening (P1 regulatory requirement)
    INITIALIZE OFAC-CHECK-RECORD
    INITIALIZE WS-OFAC-RESULT
    MOVE WIRE-ORIG-NAME TO OFAC-CHECK-NAME
    MOVE "O" TO OFAC-CHECK-TYPE
    MOVE "CHKN" TO WS-OFAC-FUNCTION
    CALL "OFACCHK0" USING WS-OFAC-FUNCTION
                          OFAC-CHECK-RECORD
                          WS-OFAC-RESULT
    IF WS-OFAC-RESULT-CODE = "E0025"
        MOVE "E0025" TO LS-WIRE-RESULT-CODE
        MOVE "OFAC match on originator"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Credit account
    MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
    ADD WIRE-AMOUNT TO ACCT-LEDGER-BAL
        ON SIZE ERROR
            MOVE "E0040" TO LS-WIRE-RESULT-CODE
            MOVE "Arithmetic overflow on wire receive"
                TO LS-WIRE-RESULT-MSG
            GOBACK
    END-ADD
    COMPUTE ACCT-AVAIL-BAL =
        ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
        ON SIZE ERROR
            MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
            MOVE "E0040" TO LS-WIRE-RESULT-CODE
            MOVE "Arithmetic overflow on wire receive"
                TO LS-WIRE-RESULT-MSG
            GOBACK
    END-COMPUTE

    *> Set wire status and receive date
    MOVE "CP" TO WIRE-STATUS
    MOVE FUNCTION CURRENT-DATE(1:8) TO WIRE-SEND-DATE
    MOVE FUNCTION CURRENT-DATE(1:8) TO WIRE-VALUE-DATE
    MOVE "I" TO WIRE-TYPE

    MOVE FUNCTION CURRENT-DATE(1:8) TO ACCT-LAST-TXN-DATE
    MOVE "E0000" TO LS-WIRE-RESULT-CODE
    MOVE "Wire transfer received" TO LS-WIRE-RESULT-MSG.

*> ---------------------------------------------------------------
*> PROCESS-COMPLETE - Confirm settlement of outgoing wire (PR->CP)
*> Called when correspondent bank confirms the wire has settled.
*> ---------------------------------------------------------------
PROCESS-COMPLETE.
    *> Validate wire reference exists
    IF WIRE-REFERENCE-NUM = SPACES
        MOVE "E0099" TO LS-WIRE-RESULT-CODE
        MOVE "Wire: invalid wire reference" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Only processing wires can be completed
    IF WIRE-STATUS NOT = "PR"
        MOVE "E0033" TO LS-WIRE-RESULT-CODE
        MOVE "Only processing wires can be completed"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Only outgoing wires use COMP (incoming use RECV directly)
    IF WIRE-TYPE NOT = "O"
        MOVE "E0037" TO LS-WIRE-RESULT-CODE
        MOVE "COMP only valid for outgoing wires"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Mark wire as completed
    MOVE "CP" TO WIRE-STATUS
    MOVE FUNCTION CURRENT-DATE(1:8) TO WIRE-VALUE-DATE

    MOVE "E0000" TO LS-WIRE-RESULT-CODE
    MOVE "Wire transfer completed" TO LS-WIRE-RESULT-MSG.

*> ---------------------------------------------------------------
*> PROCESS-REVERSE - Reverse a completed wire transfer
*> ---------------------------------------------------------------
PROCESS-REVERSE.
    *> Validate wire reference exists
    IF WIRE-REFERENCE-NUM = SPACES
        MOVE "E0099" TO LS-WIRE-RESULT-CODE
        MOVE "Wire: invalid wire reference" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Only completed wires can be reversed
    IF WIRE-STATUS NOT = "CP"
        MOVE "E0033" TO LS-WIRE-RESULT-CODE
        MOVE "Only completed wires can be reversed"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> Validate account is active (not closed or frozen)
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-WIRE-RESULT-CODE
        MOVE "Account is closed" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-WIRE-RESULT-CODE
        MOVE "Account is frozen" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-WIRE-RESULT-CODE
        MOVE "Account holder is deceased" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-WIRE-RESULT-CODE
        MOVE "Account is escheated" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-LEGAL-HOLD = "Y" AND WIRE-TYPE = "I"
        MOVE "E0035" TO LS-WIRE-RESULT-CODE
        MOVE "Account has legal hold" TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-GARNISHMENT = "Y" AND WIRE-TYPE = "I"
        MOVE "E0045" TO LS-WIRE-RESULT-CODE
        MOVE "Account under garnishment - reversal blocked"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "R" AND WIRE-TYPE = "I"
        MOVE "E0043" TO LS-WIRE-RESULT-CODE
        MOVE "Account restricted - reversal blocked"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF

    *> If incoming wire was credited, subtract from balance
    IF WIRE-TYPE = "I"
        IF WIRE-AMOUNT > ACCT-AVAIL-BAL
            MOVE "E0097" TO LS-WIRE-RESULT-CODE
            MOVE "Insufficient funds for wire reversal"
                TO LS-WIRE-RESULT-MSG
            GOBACK
        END-IF
        MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
        SUBTRACT WIRE-AMOUNT FROM ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-WIRE-RESULT-CODE
                MOVE "Arithmetic overflow on wire reversal"
                    TO LS-WIRE-RESULT-MSG
                GOBACK
        END-SUBTRACT
        COMPUTE ACCT-AVAIL-BAL =
            ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
            ON SIZE ERROR
                MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
                MOVE "E0040" TO LS-WIRE-RESULT-CODE
                MOVE "Arithmetic overflow on wire reversal"
                    TO LS-WIRE-RESULT-MSG
                GOBACK
        END-COMPUTE
        *> Track MTD low balance after reversal debit
        IF ACCT-LEDGER-BAL < ACCT-MTD-LOW-BAL
            MOVE ACCT-LEDGER-BAL TO ACCT-MTD-LOW-BAL
        END-IF
    ELSE IF WIRE-TYPE = "O"
        MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
        ADD WIRE-AMOUNT TO ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-WIRE-RESULT-CODE
                MOVE "Arithmetic overflow on wire reversal"
                    TO LS-WIRE-RESULT-MSG
                GOBACK
        END-ADD
        COMPUTE ACCT-AVAIL-BAL =
            ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
            ON SIZE ERROR
                MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
                MOVE "E0040" TO LS-WIRE-RESULT-CODE
                MOVE "Arithmetic overflow on wire reversal"
                    TO LS-WIRE-RESULT-MSG
                GOBACK
        END-COMPUTE
    ELSE
        MOVE "E0037" TO LS-WIRE-RESULT-CODE
        MOVE "Invalid wire type for reversal"
            TO LS-WIRE-RESULT-MSG
        GOBACK
    END-IF
    END-IF

    *> Set wire status to reversed
    MOVE "RV" TO WIRE-STATUS

    MOVE FUNCTION CURRENT-DATE(1:8) TO ACCT-LAST-TXN-DATE
    MOVE "E0000" TO LS-WIRE-RESULT-CODE
    MOVE "Wire transfer reversed" TO LS-WIRE-RESULT-MSG.

*> ---------------------------------------------------------------
*> PROCESS-INQUIRY - Return wire record as-is
*> ---------------------------------------------------------------
PROCESS-INQUIRY.
    MOVE "E0000" TO LS-WIRE-RESULT-CODE
    MOVE "Wire inquiry successful" TO LS-WIRE-RESULT-MSG.
