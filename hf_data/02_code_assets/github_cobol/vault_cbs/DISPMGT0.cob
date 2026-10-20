IDENTIFICATION DIVISION.
PROGRAM-ID. DISPMGT0.
*> ================================================================
*> DISPMGT0 - Dispute Management (Regulation E)
*> FILE = File new dispute, PROV = Provisional credit,
*> RSLV = Resolve dispute, INQY = Inquiry
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-CURRENT-DATE-TIME.
    05  WS-CDT-YEAR            PIC 9(4).
    05  WS-CDT-MONTH           PIC 9(2).
    05  WS-CDT-DAY             PIC 9(2).
    05  WS-CDT-HOURS           PIC 9(2).
    05  WS-CDT-MINUTES         PIC 9(2).
    05  WS-CDT-SECONDS         PIC 9(2).
    05  WS-CDT-HUNDREDTHS      PIC 9(2).
    05  WS-CDT-OFFSET-DIR      PIC X(1).
    05  WS-CDT-OFFSET-HOURS    PIC 9(2).
    05  WS-CDT-OFFSET-MINS     PIC 9(2).
01  WS-TODAY-DATE              PIC 9(8).
01  WS-NEXT-DISPUTE-ID         PIC 9(15) VALUE 1.

*> DATEUTIL interface
01  WS-DATE-FUNCTION           PIC X(4).
01  WS-DATE-INPUT.
    05  WS-DATE1               PIC 9(8).
    05  WS-DATE2               PIC 9(8).
    05  WS-DAYS-TO-ADD         PIC S9(4).
01  WS-DATE-OUTPUT.
    05  WS-RESULT-DATE         PIC 9(8).
    05  WS-RESULT-DAYS         PIC S9(8).
    05  WS-RESULT-FLAG         PIC X(1).
01  WS-DATE-RESULT.
    05  WS-DATE-RESULT-CODE    PIC X(5).
    05  WS-DATE-RESULT-MSG     PIC X(50).

*> Working fields for RSLV partial credit adjustment
01  WS-REVERSE-AMT             PIC S9(13)V99.
01  WS-SAVE-LEDGER-BAL         PIC S9(13)V99.

LINKAGE SECTION.
01  LS-DSP-FUNCTION            PIC X(4).
COPY CPYDSP.
COPY CPYACCT.
01  LS-DSP-RESULT.
    05  LS-DSP-RESULT-CODE     PIC X(5).
    05  LS-DSP-RESULT-MSG      PIC X(50).

PROCEDURE DIVISION USING LS-DSP-FUNCTION
                         DISPUTE-RECORD
                         ACCT-RECORD
                         LS-DSP-RESULT.
MAIN-LOGIC.
    MOVE "E0000" TO LS-DSP-RESULT-CODE
    MOVE SPACES TO LS-DSP-RESULT-MSG

    EVALUATE LS-DSP-FUNCTION
        WHEN "FILE"
            PERFORM DO-FILE-DISPUTE
        WHEN "PROV"
            PERFORM DO-PROVISIONAL-CREDIT
        WHEN "RSLV"
            PERFORM DO-RESOLVE-DISPUTE
        WHEN "INQY"
            PERFORM DO-INQUIRY
        WHEN OTHER
            MOVE "E0001" TO LS-DSP-RESULT-CODE
            MOVE "Invalid dispute function" TO LS-DSP-RESULT-MSG
    END-EVALUATE
    GOBACK.

*> ---------------------------------------------------------------
*> FILE - File a new dispute
*> ---------------------------------------------------------------
DO-FILE-DISPUTE.
    *> Validate dispute type
    IF DSP-DISPUTE-TYPE NOT = "UNAU"
        AND DSP-DISPUTE-TYPE NOT = "ERRO"
        AND DSP-DISPUTE-TYPE NOT = "DUPE"
        AND DSP-DISPUTE-TYPE NOT = "NORC"
        AND DSP-DISPUTE-TYPE NOT = "WRNG"
        MOVE "E0085" TO LS-DSP-RESULT-CODE
        MOVE "Invalid dispute type" TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Validate dispute amount
    IF DSP-TXN-AMOUNT NOT > 0
        MOVE "E0031" TO LS-DSP-RESULT-CODE
        MOVE "Invalid dispute amount" TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Set status to Pending
    MOVE "P" TO DSP-STATUS

    *> Set dispute date to today
    MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
    STRING WS-CDT-YEAR WS-CDT-MONTH WS-CDT-DAY
        DELIMITED BY SIZE INTO WS-TODAY-DATE
    END-STRING
    MOVE WS-TODAY-DATE TO DSP-DISPUTE-DATE

    *> Compute deadline = dispute date + 10 business days
    INITIALIZE WS-DATE-INPUT
    INITIALIZE WS-DATE-OUTPUT
    INITIALIZE WS-DATE-RESULT
    MOVE "BDAY" TO WS-DATE-FUNCTION
    MOVE WS-TODAY-DATE TO WS-DATE1
    MOVE +10 TO WS-DAYS-TO-ADD
    CALL "DATEUTIL" USING WS-DATE-FUNCTION
                          WS-DATE-INPUT
                          WS-DATE-OUTPUT
                          WS-DATE-RESULT
    IF WS-DATE-RESULT-CODE NOT = "E0000"
        MOVE WS-DATE-RESULT-CODE TO LS-DSP-RESULT-CODE
        MOVE WS-DATE-RESULT-MSG TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF
    MOVE WS-RESULT-DATE TO DSP-DEADLINE-DATE

    *> Assign dispute ID (auto-increment)
    MOVE WS-NEXT-DISPUTE-ID TO DSP-DISPUTE-ID
    ADD 1 TO WS-NEXT-DISPUTE-ID
        ON SIZE ERROR
            MOVE "E0040" TO LS-DSP-RESULT-CODE
            MOVE "Arithmetic overflow on dispute ID"
                TO LS-DSP-RESULT-MSG
            GOBACK
    END-ADD

    MOVE "E0000" TO LS-DSP-RESULT-CODE
    MOVE "Dispute filed successfully" TO LS-DSP-RESULT-MSG.

*> ---------------------------------------------------------------
*> PROV - Issue provisional credit
*> ---------------------------------------------------------------
DO-PROVISIONAL-CREDIT.
    *> Validate dispute exists
    IF DSP-DISPUTE-ID = 0
        MOVE "E0087" TO LS-DSP-RESULT-CODE
        MOVE "Dispute not found" TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Validate status is P or I (not already resolved/denied/credited)
    IF DSP-STATUS NOT = "P" AND DSP-STATUS NOT = "I"
        MOVE "E0086" TO LS-DSP-RESULT-CODE
        MOVE "Invalid dispute status for operation"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Validate account is not closed or frozen
    IF ACCT-STATUS = "C"
        MOVE "E0011" TO LS-DSP-RESULT-CODE
        MOVE "Account closed - cannot issue credit"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "F"
        MOVE "E0012" TO LS-DSP-RESULT-CODE
        MOVE "Account frozen - cannot issue credit"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-STATUS = "E"
        MOVE "E0044" TO LS-DSP-RESULT-CODE
        MOVE "Account escheated - cannot issue credit"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF
    IF ACCT-DECEASED = "Y"
        MOVE "E0036" TO LS-DSP-RESULT-CODE
        MOVE "Account holder deceased - cannot issue credit"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Set provisional amount and date
    MOVE DSP-TXN-AMOUNT TO DSP-PROVISIONAL-AMT

    MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
    STRING WS-CDT-YEAR WS-CDT-MONTH WS-CDT-DAY
        DELIMITED BY SIZE INTO WS-TODAY-DATE
    END-STRING
    MOVE WS-TODAY-DATE TO DSP-PROVISIONAL-DATE

    *> Credit account (before setting status to avoid inconsistency)
    MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
    ADD DSP-PROVISIONAL-AMT TO ACCT-LEDGER-BAL
        ON SIZE ERROR
            MOVE "E0040" TO LS-DSP-RESULT-CODE
            MOVE "Arithmetic overflow on provisional credit"
                TO LS-DSP-RESULT-MSG
            GOBACK
    END-ADD
    COMPUTE ACCT-AVAIL-BAL =
        ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
        ON SIZE ERROR
            MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
            MOVE "E0040" TO LS-DSP-RESULT-CODE
            MOVE "Arithmetic overflow on available balance"
                TO LS-DSP-RESULT-MSG
            GOBACK
    END-COMPUTE

    *> Set status to Credited only after balance update succeeds
    MOVE "C" TO DSP-STATUS

    MOVE "E0000" TO LS-DSP-RESULT-CODE
    MOVE "Provisional credit issued" TO LS-DSP-RESULT-MSG.

*> ---------------------------------------------------------------
*> RSLV - Resolve dispute
*> ---------------------------------------------------------------
DO-RESOLVE-DISPUTE.
    *> Validate dispute exists
    IF DSP-DISPUTE-ID = 0
        MOVE "E0087" TO LS-DSP-RESULT-CODE
        MOVE "Dispute not found" TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Validate dispute is in a resolvable status
    IF DSP-STATUS NOT = "P" AND DSP-STATUS NOT = "I"
        AND DSP-STATUS NOT = "C"
        MOVE "E0086" TO LS-DSP-RESULT-CODE
        MOVE "Dispute not in resolvable status"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    *> Set resolution date
    MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE-TIME
    STRING WS-CDT-YEAR WS-CDT-MONTH WS-CDT-DAY
        DELIMITED BY SIZE INTO WS-TODAY-DATE
    END-STRING
    MOVE WS-TODAY-DATE TO DSP-RESOLUTION-DATE

    *> Reg E enforcement: if 10 business-day deadline has passed
    *> and no provisional credit was issued (status "P" or "I"),
    *> require PROV before RSLV. 12 CFR 1005.11(c)(1).
    IF (DSP-STATUS = "P" OR DSP-STATUS = "I")
        AND DSP-DEADLINE-DATE > 0
        AND WS-TODAY-DATE > DSP-DEADLINE-DATE
        MOVE "E0100" TO LS-DSP-RESULT-CODE
        MOVE "Reg E: provisional credit required past deadline"
            TO LS-DSP-RESULT-MSG
        GOBACK
    END-IF

    EVALUATE DSP-RESOLUTION-CODE
        WHEN "AP"
            *> Approved: keep provisional credit, mark resolved
            MOVE "R" TO DSP-STATUS
        WHEN "DN"
            *> Denied: reverse provisional credit
            IF DSP-PROVISIONAL-AMT > 0
                MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
                SUBTRACT DSP-PROVISIONAL-AMT FROM ACCT-LEDGER-BAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-DSP-RESULT-CODE
                        MOVE "Arithmetic overflow on credit reversal"
                            TO LS-DSP-RESULT-MSG
                        GOBACK
                END-SUBTRACT
                COMPUTE ACCT-AVAIL-BAL =
                    ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
                    ON SIZE ERROR
                        MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
                        MOVE "E0040" TO LS-DSP-RESULT-CODE
                        MOVE "Arithmetic overflow on available balance"
                            TO LS-DSP-RESULT-MSG
                        GOBACK
                END-COMPUTE
            END-IF
            MOVE "D" TO DSP-STATUS
        WHEN "PA"
            *> Partial: reverse difference between provisional
            *> and the partial amount the caller set in
            *> DSP-TXN-AMOUNT (the approved partial amount)
            IF DSP-TXN-AMOUNT <= 0
                MOVE "E0031" TO LS-DSP-RESULT-CODE
                MOVE "Partial resolution amount must be positive"
                    TO LS-DSP-RESULT-MSG
                GOBACK
            END-IF
            IF DSP-TXN-AMOUNT > DSP-PROVISIONAL-AMT
                MOVE "E0002" TO LS-DSP-RESULT-CODE
                MOVE "Partial amount exceeds provisional credit"
                    TO LS-DSP-RESULT-MSG
                GOBACK
            END-IF
            IF DSP-PROVISIONAL-AMT > DSP-TXN-AMOUNT
                COMPUTE WS-REVERSE-AMT =
                    DSP-PROVISIONAL-AMT - DSP-TXN-AMOUNT
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-DSP-RESULT-CODE
                        MOVE "Arithmetic overflow on partial reversal"
                            TO LS-DSP-RESULT-MSG
                        GOBACK
                END-COMPUTE
                MOVE ACCT-LEDGER-BAL TO WS-SAVE-LEDGER-BAL
                SUBTRACT WS-REVERSE-AMT FROM ACCT-LEDGER-BAL
                    ON SIZE ERROR
                        MOVE "E0040" TO LS-DSP-RESULT-CODE
                        MOVE "Arithmetic overflow on partial reversal"
                            TO LS-DSP-RESULT-MSG
                        GOBACK
                END-SUBTRACT
                COMPUTE ACCT-AVAIL-BAL =
                    ACCT-LEDGER-BAL - ACCT-HOLD-AMOUNT
                    ON SIZE ERROR
                        MOVE WS-SAVE-LEDGER-BAL TO ACCT-LEDGER-BAL
                        MOVE "E0040" TO LS-DSP-RESULT-CODE
                        MOVE "Arithmetic overflow on available balance"
                            TO LS-DSP-RESULT-MSG
                        GOBACK
                END-COMPUTE
            END-IF
            MOVE "R" TO DSP-STATUS
        WHEN OTHER
            MOVE "E0086" TO LS-DSP-RESULT-CODE
            MOVE "Invalid resolution code" TO LS-DSP-RESULT-MSG
            GOBACK
    END-EVALUATE

    MOVE "E0000" TO LS-DSP-RESULT-CODE
    MOVE "Dispute resolved" TO LS-DSP-RESULT-MSG.

*> ---------------------------------------------------------------
*> INQY - Inquiry (return dispute record as-is)
*> ---------------------------------------------------------------
DO-INQUIRY.
    MOVE "E0000" TO LS-DSP-RESULT-CODE
    MOVE "Dispute inquiry complete" TO LS-DSP-RESULT-MSG.
