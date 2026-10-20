IDENTIFICATION DIVISION.
PROGRAM-ID. ACHRECV0.
*> ================================================================
*> ACHRECV0 - ACH Incoming File Processor
*> Processes credits/debits, handles returns (R01-R09)
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-IS-CREDIT           PIC X(1).
01  WS-IS-DEBIT            PIC X(1).
01  WS-SAVE-LEDGER-BAL     PIC S9(13)V99.

*> Reg D check linkage areas
01  WS-REGD-REQUEST.
    05  WS-RD-TXN-CHANNEL  PIC X(2).
    05  WS-RD-TXN-TYPE     PIC X(3).
    05  WS-RD-CURRENT-COUNT PIC 9(3).
01  WS-REGD-RESULT.
    05  WS-RD-RESULT-CODE  PIC X(5).
    05  WS-RD-RESULT-MSG   PIC X(50).
    05  WS-RD-ALLOWED      PIC X(1).
    05  WS-RD-NEW-COUNT    PIC 9(3).
    05  WS-RD-LIMIT-REACHED PIC X(1).

*> Audit trail linkage areas
01  WS-AUDIT-FUNCTION      PIC X(4).
COPY CPYAUDT.
01  WS-AUDIT-RESULT.
    05  WS-AUDT-RESULT-CODE  PIC X(5).
    05  WS-AUDT-RESULT-MSG   PIC X(50).

*> OFAC screening areas
COPY CPYOFAC.
01  WS-OFAC-FUNCTION          PIC X(4).
01  WS-OFAC-RESULT.
    05  WS-OFAC-RESULT-CODE   PIC X(5).
    05  WS-OFAC-RESULT-MSG    PIC X(50).

LINKAGE SECTION.
01  LS-ACH-ENTRY.
    05  LS-ACH-RECORD-TYPE       PIC X(1).
    05  LS-ACH-TXN-CODE          PIC 9(2).
    *> 22 = Credit, 27 = Debit,
    *> 32 = Credit savings, 37 = Debit savings
    05  LS-ACH-ROUTING-NUM       PIC 9(9).
    05  LS-ACH-ACCT-NUMBER       PIC X(17).
    05  LS-ACH-AMOUNT            PIC S9(13)V99.
    05  LS-ACH-INDIV-NAME        PIC X(22).
    05  LS-ACH-TRACE-NUMBER      PIC X(15).
    05  LS-ACH-ADDENDA-FLAG      PIC X(1).
    *> Batch control fields
    05  LS-ACH-BATCH-COUNT       PIC 9(6).
    05  LS-ACH-BATCH-DR-TOTAL    PIC S9(13)V99.
    05  LS-ACH-BATCH-CR-TOTAL    PIC S9(13)V99.
    05  LS-ACH-BATCH-HASH        PIC 9(10).
COPY CPYACCT.
01  LS-ACH-RETURN-INFO.
    05  LS-ACH-RETURN-CODE       PIC X(3).
    *> R01 = NSF, R02 = Closed, R03 = No Account,
    *> R04 = Invalid Acct Number, R06 = Deceased,
    *> R07 = Auth Revoked, R08 = Stop Payment,
    *> R09 = Reg D violation
    05  LS-ACH-RETURN-REASON     PIC X(30).
    05  LS-ACH-RETURN-FLAG       PIC X(1).
01  LS-ACH-RESULT.
    05  LS-ACH-RESULT-CODE        PIC X(5).
    05  LS-ACH-RESULT-MSG         PIC X(50).

PROCEDURE DIVISION USING LS-ACH-ENTRY
                         ACCT-RECORD
                         LS-ACH-RETURN-INFO
                         LS-ACH-RESULT.
MAIN-PROCESS.
    *> Initialize outputs
    MOVE SPACES TO LS-ACH-RETURN-CODE
    MOVE SPACES TO LS-ACH-RETURN-REASON
    MOVE "N" TO LS-ACH-RETURN-FLAG
    MOVE "E0000" TO LS-ACH-RESULT-CODE
    MOVE SPACES TO LS-ACH-RESULT-MSG

    *> Determine transaction type
    MOVE "N" TO WS-IS-CREDIT
    MOVE "N" TO WS-IS-DEBIT
    IF LS-ACH-TXN-CODE = 22 OR LS-ACH-TXN-CODE = 32
        MOVE "Y" TO WS-IS-CREDIT
    END-IF
    IF LS-ACH-TXN-CODE = 27 OR LS-ACH-TXN-CODE = 37
        MOVE "Y" TO WS-IS-DEBIT
    END-IF

    *> Reject unsupported transaction codes
    IF WS-IS-CREDIT = "N" AND WS-IS-DEBIT = "N"
        MOVE "E0037" TO LS-ACH-RESULT-CODE
        MOVE "UNSUPPORTED ACH TRANSACTION CODE"
            TO LS-ACH-RESULT-MSG
        GOBACK
    END-IF

    *> Step 1: Validate ACH amount
    PERFORM VALIDATE-AMOUNT
    IF LS-ACH-RESULT-CODE NOT = "E0000"
        GOBACK
    END-IF

    *> Step 2: Batch control validation
    PERFORM CHECK-BATCH-TOTALS
    IF LS-ACH-RESULT-CODE NOT = "E0000"
        GOBACK
    END-IF

    *> Step 3: Account validation
    PERFORM CHECK-ACCOUNT
    IF LS-ACH-RETURN-FLAG = "Y"
        GOBACK
    END-IF

    *> Step 3b: OFAC screening on originator
    PERFORM CHECK-OFAC
    IF LS-ACH-RESULT-CODE NOT = "E0000"
        GOBACK
    END-IF

    *> Step 4: Funds check for debits
    IF WS-IS-DEBIT = "Y"
        PERFORM CHECK-FUNDS
        IF LS-ACH-RETURN-FLAG = "Y"
            GOBACK
        END-IF
    END-IF

    *> Step 5: Reg D check for debits from savings/MMA
    IF WS-IS-DEBIT = "Y"
        IF ACCT-SUB-TYPE = "SV" OR ACCT-SUB-TYPE = "MM"
            PERFORM CHECK-REG-D
            IF LS-ACH-RETURN-FLAG = "Y"
                GOBACK
            END-IF
        END-IF
    END-IF

    *> Step 6: Process the transaction
    PERFORM PROCESS-TRANSACTION

    *> Step 7: Write audit trail for successful transaction
    PERFORM WRITE-AUDIT-TRAIL
    GOBACK.

*> ---------------------------------------------------------------
*> CHECK-BATCH-TOTALS - Validate batch control totals
*> ---------------------------------------------------------------
CHECK-BATCH-TOTALS.
    *> Zero batch count is invalid — reject malformed ACH batch
    IF LS-ACH-BATCH-COUNT = 0
        MOVE "E0094" TO LS-ACH-RESULT-CODE
        MOVE "INVALID BATCH: ENTRY COUNT IS ZERO"
            TO LS-ACH-RESULT-MSG
        EXIT PARAGRAPH
    END-IF
    *> Single-entry batch: entry amount must equal batch total
    IF LS-ACH-BATCH-COUNT = 1
        IF WS-IS-CREDIT = "Y"
            IF LS-ACH-AMOUNT NOT = LS-ACH-BATCH-CR-TOTAL
                MOVE "E0094" TO LS-ACH-RESULT-CODE
                MOVE "BATCH CONTROL TOTAL MISMATCH"
                    TO LS-ACH-RESULT-MSG
            END-IF
        END-IF
        IF WS-IS-DEBIT = "Y"
            IF LS-ACH-AMOUNT NOT = LS-ACH-BATCH-DR-TOTAL
                MOVE "E0094" TO LS-ACH-RESULT-CODE
                MOVE "BATCH CONTROL TOTAL MISMATCH"
                    TO LS-ACH-RESULT-MSG
            END-IF
        END-IF
    END-IF
    *> Multi-entry batch: no single entry can exceed its batch total
    IF LS-ACH-BATCH-COUNT > 1
        IF WS-IS-CREDIT = "Y"
            AND LS-ACH-BATCH-CR-TOTAL > 0
            IF LS-ACH-AMOUNT > LS-ACH-BATCH-CR-TOTAL
                MOVE "E0094" TO LS-ACH-RESULT-CODE
                MOVE "ENTRY EXCEEDS BATCH CREDIT TOTAL"
                    TO LS-ACH-RESULT-MSG
            END-IF
        END-IF
        IF WS-IS-DEBIT = "Y"
            AND LS-ACH-BATCH-DR-TOTAL > 0
            IF LS-ACH-AMOUNT > LS-ACH-BATCH-DR-TOTAL
                MOVE "E0094" TO LS-ACH-RESULT-CODE
                MOVE "ENTRY EXCEEDS BATCH DEBIT TOTAL"
                    TO LS-ACH-RESULT-MSG
            END-IF
        END-IF
    END-IF.

*> ---------------------------------------------------------------
*> CHECK-ACCOUNT - Validate account exists and is usable
*> ---------------------------------------------------------------
CHECK-ACCOUNT.
    *> Check for invalid account number format (all spaces/zeros)
    IF LS-ACH-ACCT-NUMBER = SPACES
        OR LS-ACH-ACCT-NUMBER = "00000000000000000"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R04" TO LS-ACH-RETURN-CODE
        MOVE "INVALID ACCOUNT NUMBER" TO LS-ACH-RETURN-REASON
    *> Check for non-existent account
    ELSE IF ACCT-NUMBER = 0 OR ACCT-STATUS = SPACES
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R03" TO LS-ACH-RETURN-CODE
        MOVE "NO ACCOUNT ON FILE" TO LS-ACH-RETURN-REASON
    *> Check for deceased account holder
    ELSE IF ACCT-DECEASED = "Y"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R06" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT HOLDER DECEASED" TO LS-ACH-RETURN-REASON
    *> Check for closed account
    ELSE IF ACCT-STATUS = "C"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R02" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT CLOSED" TO LS-ACH-RETURN-REASON
    *> Check for frozen account
    ELSE IF ACCT-STATUS = "F"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R16" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT FROZEN" TO LS-ACH-RETURN-REASON
    *> Check for escheated account
    ELSE IF ACCT-STATUS = "E"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R16" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT ESCHEATED" TO LS-ACH-RETURN-REASON
    *> Check for legal hold on debits (credits still allowed)
    ELSE IF ACCT-LEGAL-HOLD = "Y"
        AND WS-IS-DEBIT = "Y"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R16" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT UNDER LEGAL HOLD" TO LS-ACH-RETURN-REASON
    *> Check for authorization revoked (debits to restricted acct)
    ELSE IF ACCT-STATUS = "R"
        AND WS-IS-DEBIT = "Y"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R07" TO LS-ACH-RETURN-CODE
        MOVE "AUTH REVOKED BY RECEIVER" TO LS-ACH-RETURN-REASON
    *> Check for stop payment on debits
    ELSE IF ACCT-STOP-PAYS-ACTIVE > 0
        AND WS-IS-DEBIT = "Y"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R08" TO LS-ACH-RETURN-CODE
        MOVE "STOP PAYMENT ON ITEM" TO LS-ACH-RETURN-REASON
    *> Check for garnishment on debits (preserve funds for court order)
    ELSE IF ACCT-GARNISHMENT = "Y"
        AND WS-IS-DEBIT = "Y"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R16" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT UNDER GARNISHMENT" TO LS-ACH-RETURN-REASON
    *> Check for dormant account debits (consistent with TXNPOST0)
    ELSE IF ACCT-STATUS = "D"
        AND WS-IS-DEBIT = "Y"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R16" TO LS-ACH-RETURN-CODE
        MOVE "ACCOUNT DORMANT" TO LS-ACH-RETURN-REASON
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF
    END-IF.

*> ---------------------------------------------------------------
*> CHECK-FUNDS - Verify sufficient funds for debits
*> ---------------------------------------------------------------
CHECK-FUNDS.
    IF LS-ACH-AMOUNT > ACCT-AVAIL-BAL
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R01" TO LS-ACH-RETURN-CODE
        MOVE "INSUFFICIENT FUNDS" TO LS-ACH-RETURN-REASON
    END-IF.

*> ---------------------------------------------------------------
*> PROCESS-TRANSACTION - Apply credit or debit to account
*> ---------------------------------------------------------------
PROCESS-TRANSACTION.
    MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
    IF WS-IS-CREDIT = "Y"
        ADD LS-ACH-AMOUNT TO ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-ACH-RESULT-CODE
                MOVE "ACH overflow on balance"
                    TO LS-ACH-RESULT-MSG
                GOBACK
        END-ADD
    END-IF
    IF WS-IS-DEBIT = "Y"
        SUBTRACT LS-ACH-AMOUNT FROM ACCT-LEDGER-BAL
            ON SIZE ERROR
                MOVE "E0040" TO LS-ACH-RESULT-CODE
                MOVE "ACH overflow on balance"
                    TO LS-ACH-RESULT-MSG
                GOBACK
        END-SUBTRACT
    END-IF
    *> Bug fix: Update available balance to mirror TXNPOST0
    COMPUTE ACCT-AVAIL-BAL =
        ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
        ON SIZE ERROR
            MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
            MOVE "E0040" TO LS-ACH-RESULT-CODE
            MOVE "ACH overflow on balance"
                TO LS-ACH-RESULT-MSG
            GOBACK
    END-COMPUTE
    *> Track MTD low balance after ACH balance change
    IF ACCT-LEDGER-BAL < ACCT-MTD-LOW-BAL
        MOVE ACCT-LEDGER-BAL TO ACCT-MTD-LOW-BAL
    END-IF
    MOVE FUNCTION CURRENT-DATE(1:8) TO ACCT-LAST-TXN-DATE
    MOVE "N" TO LS-ACH-RETURN-FLAG
    MOVE "E0000" TO LS-ACH-RESULT-CODE
    MOVE "ACH TRANSACTION PROCESSED" TO LS-ACH-RESULT-MSG.

*> ---------------------------------------------------------------
*> VALIDATE-AMOUNT - Ensure ACH amount is positive
*> ---------------------------------------------------------------
VALIDATE-AMOUNT.
    IF LS-ACH-AMOUNT = 0
        MOVE "E0031" TO LS-ACH-RESULT-CODE
        MOVE "INVALID ACH AMOUNT - ZERO" TO LS-ACH-RESULT-MSG
    ELSE IF LS-ACH-AMOUNT < 0
        MOVE "E0032" TO LS-ACH-RESULT-CODE
        MOVE "INVALID ACH AMOUNT - NEGATIVE" TO LS-ACH-RESULT-MSG
    END-IF
    END-IF.

*> ---------------------------------------------------------------
*> CHECK-REG-D - Regulation D transfer limit for savings/MMA
*> ---------------------------------------------------------------
CHECK-REG-D.
    INITIALIZE WS-REGD-REQUEST
    INITIALIZE WS-REGD-RESULT
    MOVE "AC" TO WS-RD-TXN-CHANNEL
    MOVE "ACH" TO WS-RD-TXN-TYPE
    MOVE ACCT-OL-TXN-COUNT-MTD TO WS-RD-CURRENT-COUNT
    CALL "REGDCHK0" USING ACCT-RECORD
                          WS-REGD-REQUEST
                          WS-REGD-RESULT
    IF WS-RD-ALLOWED = "N"
        MOVE "Y" TO LS-ACH-RETURN-FLAG
        MOVE "R09" TO LS-ACH-RETURN-CODE
        MOVE "REG D TRANSFER LIMIT EXCEEDED"
            TO LS-ACH-RETURN-REASON
    END-IF
    IF WS-RD-ALLOWED = "Y"
        MOVE WS-RD-NEW-COUNT TO ACCT-OL-TXN-COUNT-MTD
    END-IF.

*> ---------------------------------------------------------------
*> CHECK-OFAC - Screen ACH originator against OFAC SDN list
*> ---------------------------------------------------------------
CHECK-OFAC.
    INITIALIZE OFAC-CHECK-RECORD
    INITIALIZE WS-OFAC-RESULT
    MOVE LS-ACH-INDIV-NAME TO OFAC-CHECK-NAME
    MOVE "O" TO OFAC-CHECK-TYPE
    MOVE "CHKN" TO WS-OFAC-FUNCTION
    CALL "OFACCHK0" USING WS-OFAC-FUNCTION
                          OFAC-CHECK-RECORD
                          WS-OFAC-RESULT
    IF WS-OFAC-RESULT-CODE = "E0025"
        MOVE "E0025" TO LS-ACH-RESULT-CODE
        MOVE "OFAC match on ACH originator"
            TO LS-ACH-RESULT-MSG
    END-IF.

*> ---------------------------------------------------------------
*> WRITE-AUDIT-TRAIL - Log successful ACH transaction
*> ---------------------------------------------------------------
WRITE-AUDIT-TRAIL.
    INITIALIZE AUDIT-RECORD
    INITIALIZE WS-AUDIT-RESULT
    MOVE "WRIT" TO WS-AUDIT-FUNCTION
    MOVE "SYSTEM" TO AUDIT-USER-ID
    MOVE "ACHRECV0" TO AUDIT-PROGRAM-ID
    MOVE "ACH " TO AUDIT-FUNCTION
    MOVE "ACCT" TO AUDIT-ENTITY-TYPE
    MOVE ACCT-NUMBER TO AUDIT-ENTITY-KEY
    MOVE "ACH transaction processed"
        TO AUDIT-DESCRIPTION
    CALL "AUDTLOG0" USING WS-AUDIT-FUNCTION
                          AUDIT-RECORD
                          WS-AUDIT-RESULT.
