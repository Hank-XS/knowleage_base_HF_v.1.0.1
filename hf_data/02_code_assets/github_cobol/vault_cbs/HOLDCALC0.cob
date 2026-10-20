IDENTIFICATION DIVISION.
PROGRAM-ID. HOLDCALC0.
*> ================================================================
*> HOLDCALC0 - Regulation CC Hold Calculation
*> Determines hold amounts and release dates per Reg CC
*> ================================================================

DATA DIVISION.
WORKING-STORAGE SECTION.
COPY CPYCONST.
COPY CPYERR.

01  WS-DEPOSIT-AMT            PIC S9(13)V99.
01  WS-NEXT-DAY-THRESHOLD     PIC S9(13)V99.

*> Date arithmetic fields
01  WS-DEP-DATE-INT            PIC 9(8).
01  WS-OPEN-DATE-INT           PIC 9(8).
01  WS-DEP-DATE-YYYYMMDD.
    05  WS-DEP-YYYY            PIC 9(4).
    05  WS-DEP-MM              PIC 9(2).
    05  WS-DEP-DD              PIC 9(2).
01  WS-OPEN-DATE-YYYYMMDD.
    05  WS-OPEN-YYYY           PIC 9(4).
    05  WS-OPEN-MM             PIC 9(2).
    05  WS-OPEN-DD             PIC 9(2).
01  WS-DEP-INTEGER-DATE        PIC 9(8).
01  WS-OPEN-INTEGER-DATE       PIC 9(8).
01  WS-DAYS-DIFF               PIC S9(8).

01  WS-EXCEPTION-FLAG          PIC X(1).
01  WS-HOLD-REASON             PIC X(2).
01  WS-HOLD-DAYS               PIC 9(2).

*> DATEUTIL CALL fields
01  WS-DU-FUNCTION             PIC X(4).
01  WS-DU-DATE-INPUT.
    05  WS-DU-DATE1            PIC 9(8).
    05  WS-DU-DATE2            PIC 9(8).
    05  WS-DU-DAYS-TO-ADD      PIC S9(4).
01  WS-DU-DATE-OUTPUT.
    05  WS-DU-RESULT-DATE      PIC 9(8).
    05  WS-DU-RESULT-DAYS      PIC S9(8).
    05  WS-DU-RESULT-FLAG      PIC X(1).
01  WS-DU-DATE-RESULT.
    05  WS-DU-DATE-RESULT-CODE PIC X(5).
    05  WS-DU-DATE-RESULT-MSG  PIC X(50).

LINKAGE SECTION.
01  LS-HOLD-REQUEST.
    05  LS-HR-ACCT-NUMBER         PIC 9(12).
    05  LS-HR-DEPOSIT-AMT         PIC S9(13)V99.
    05  LS-HR-CHECK-TYPE          PIC X(2).
    *> LC = Local, NL = Non-local, TR = Treasury,
    *> CA = Cashier, CS = Cash, WR = Wire
    05  LS-HR-DEPOSIT-DATE        PIC 9(8).
    05  LS-HR-ACCT-OPEN-DATE      PIC 9(8).
    05  LS-HR-IS-REDEPOSIT        PIC X(1).
    05  LS-HR-REPEATED-OD         PIC X(1).
COPY CPYHOLD.
01  LS-HOLD-RESULT.
    05  LS-HOLD-RESULT-CODE       PIC X(5).
    05  LS-HOLD-RESULT-MSG        PIC X(50).
    05  LS-HOLD-NEXT-DAY-AMT      PIC S9(13)V99.
    05  LS-HOLD-REMAINING-AMT     PIC S9(13)V99.
    05  LS-HOLD-RELEASE-DT        PIC 9(8).
    05  LS-HOLD-EXCEPTION-FLAG    PIC X(1).

PROCEDURE DIVISION USING LS-HOLD-REQUEST
                         HOLD-RECORD
                         LS-HOLD-RESULT.
MAIN-LOGIC.
    INITIALIZE LS-HOLD-RESULT
    MOVE "N" TO WS-EXCEPTION-FLAG
    MOVE "ND" TO WS-HOLD-REASON
    MOVE LS-HR-DEPOSIT-AMT TO WS-DEPOSIT-AMT

    EVALUATE LS-HR-CHECK-TYPE
        WHEN "CS"
            PERFORM CALC-CASH-WIRE
        WHEN "WR"
            PERFORM CALC-CASH-WIRE
        WHEN "TR"
            PERFORM CALC-TREASURY-CASHIER
        WHEN "CA"
            PERFORM CALC-TREASURY-CASHIER
        WHEN "LC"
            PERFORM CALC-CHECK-DEPOSIT
        WHEN "NL"
            PERFORM CALC-CHECK-DEPOSIT
        WHEN OTHER
            PERFORM CALC-CHECK-DEPOSIT
    END-EVALUATE

    *> Bail out if release date computation failed
    IF LS-HOLD-RESULT-CODE NOT = SPACES
        AND LS-HOLD-RESULT-CODE NOT = "E0000"
        GOBACK
    END-IF

    *> Check exception conditions for check deposits only
    IF LS-HR-CHECK-TYPE NOT = "CS"
        AND LS-HR-CHECK-TYPE NOT = "WR"
        PERFORM CHECK-EXCEPTIONS
    END-IF

    *> Extend hold period for exception conditions (Reg CC 229.13)
    IF WS-EXCEPTION-FLAG = "Y"
        ADD WS-REGCC-EXCEPTION-DAYS TO WS-HOLD-DAYS
        PERFORM COMPUTE-RELEASE-DATE
        IF LS-HOLD-RESULT-CODE NOT = SPACES
            AND LS-HOLD-RESULT-CODE NOT = "E0000"
            GOBACK
        END-IF
    END-IF

    *> Populate hold record
    MOVE LS-HR-ACCT-NUMBER TO HOLD-ACCT-NUMBER
    MOVE "CC" TO HOLD-TYPE
    MOVE LS-HOLD-REMAINING-AMT TO HOLD-AMOUNT
    MOVE LS-HR-DEPOSIT-DATE TO HOLD-PLACE-DATE
    MOVE LS-HOLD-RELEASE-DT TO HOLD-RELEASE-DATE
    MOVE WS-HOLD-REASON TO HOLD-REASON-CODE
    MOVE "A" TO HOLD-STATUS

    MOVE WS-EXCEPTION-FLAG TO LS-HOLD-EXCEPTION-FLAG
    MOVE "E0000" TO LS-HOLD-RESULT-CODE
    MOVE "Hold calculation complete" TO LS-HOLD-RESULT-MSG
    GOBACK.

*> ---------------------------------------------------------------
*> Cash and Wire: no hold, full next-day availability
*> ---------------------------------------------------------------
CALC-CASH-WIRE.
    MOVE WS-DEPOSIT-AMT TO LS-HOLD-NEXT-DAY-AMT
    MOVE 0 TO LS-HOLD-REMAINING-AMT
    MOVE LS-HR-DEPOSIT-DATE TO LS-HOLD-RELEASE-DT.

*> ---------------------------------------------------------------
*> Treasury / Cashier checks: $5,525 next-day threshold
*> ---------------------------------------------------------------
CALC-TREASURY-CASHIER.
    IF WS-DEPOSIT-AMT <= WS-REGCC-TREASURY-AMT
        MOVE WS-DEPOSIT-AMT TO LS-HOLD-NEXT-DAY-AMT
        MOVE 0 TO LS-HOLD-REMAINING-AMT
    ELSE
        MOVE WS-REGCC-TREASURY-AMT TO LS-HOLD-NEXT-DAY-AMT
        SUBTRACT WS-REGCC-TREASURY-AMT FROM WS-DEPOSIT-AMT
            GIVING LS-HOLD-REMAINING-AMT
    END-IF
    *> Treasury/cashier: 2 business days hold
    MOVE 2 TO WS-HOLD-DAYS
    PERFORM COMPUTE-RELEASE-DATE.

*> ---------------------------------------------------------------
*> Check deposits (LC, NL): $225 next-day threshold
*> ---------------------------------------------------------------
CALC-CHECK-DEPOSIT.
    IF WS-DEPOSIT-AMT <= WS-REGCC-NEXT-DAY-AMT
        MOVE WS-DEPOSIT-AMT TO LS-HOLD-NEXT-DAY-AMT
        MOVE 0 TO LS-HOLD-REMAINING-AMT
    ELSE
        MOVE WS-REGCC-NEXT-DAY-AMT TO LS-HOLD-NEXT-DAY-AMT
        SUBTRACT WS-REGCC-NEXT-DAY-AMT FROM WS-DEPOSIT-AMT
            GIVING LS-HOLD-REMAINING-AMT
    END-IF

    IF LS-HR-CHECK-TYPE = "LC"
        MOVE WS-REGCC-LOCAL-DAYS TO WS-HOLD-DAYS
    ELSE
        MOVE WS-REGCC-NONLOCAL-DAYS TO WS-HOLD-DAYS
    END-IF
    PERFORM COMPUTE-RELEASE-DATE.

*> ---------------------------------------------------------------
*> Check exception conditions (Reg CC)
*> ---------------------------------------------------------------
CHECK-EXCEPTIONS.
    *> Large deposit: strictly greater than $5,525.00
    IF WS-DEPOSIT-AMT > WS-REGCC-LARGE-DEP-AMT
        MOVE "Y" TO WS-EXCEPTION-FLAG
        MOVE "LD" TO WS-HOLD-REASON
    END-IF

    *> New account: deposit date - account open date < 30 days
    PERFORM CALC-DAYS-BETWEEN
    IF WS-DAYS-DIFF < WS-REGCC-NEW-ACCT-DAYS
        MOVE "Y" TO WS-EXCEPTION-FLAG
        MOVE "NA" TO WS-HOLD-REASON
    END-IF

    *> Redeposited check
    IF LS-HR-IS-REDEPOSIT = "Y"
        MOVE "Y" TO WS-EXCEPTION-FLAG
        MOVE "RD" TO WS-HOLD-REASON
    END-IF

    *> Repeated overdraft
    IF LS-HR-REPEATED-OD = "Y"
        MOVE "Y" TO WS-EXCEPTION-FLAG
        MOVE "OD" TO WS-HOLD-REASON
    END-IF.

*> ---------------------------------------------------------------
*> Calculate days between account open date and deposit date
*> Simple date difference using integer-of-date intrinsic
*> ---------------------------------------------------------------
CALC-DAYS-BETWEEN.
    MOVE LS-HR-DEPOSIT-DATE TO WS-DEP-DATE-INT
    MOVE LS-HR-ACCT-OPEN-DATE TO WS-OPEN-DATE-INT
    COMPUTE WS-DAYS-DIFF =
        FUNCTION INTEGER-OF-DATE(WS-DEP-DATE-INT)
      - FUNCTION INTEGER-OF-DATE(WS-OPEN-DATE-INT).

*> ---------------------------------------------------------------
*> Compute hold release date using DATEUTIL business-day addition
*> Input: LS-HR-DEPOSIT-DATE, WS-HOLD-DAYS
*> Output: LS-HOLD-RELEASE-DT
*> ---------------------------------------------------------------
COMPUTE-RELEASE-DATE.
    MOVE "BDAY" TO WS-DU-FUNCTION
    MOVE LS-HR-DEPOSIT-DATE TO WS-DU-DATE1
    MOVE 0 TO WS-DU-DATE2
    MOVE WS-HOLD-DAYS TO WS-DU-DAYS-TO-ADD
    INITIALIZE WS-DU-DATE-OUTPUT
    INITIALIZE WS-DU-DATE-RESULT
    CALL "DATEUTIL" USING WS-DU-FUNCTION
                          WS-DU-DATE-INPUT
                          WS-DU-DATE-OUTPUT
                          WS-DU-DATE-RESULT
    IF WS-DU-DATE-RESULT-CODE NOT = "E0000"
        MOVE WS-DU-DATE-RESULT-CODE TO LS-HOLD-RESULT-CODE
        MOVE WS-DU-DATE-RESULT-MSG TO LS-HOLD-RESULT-MSG
        EXIT PARAGRAPH
    END-IF
    MOVE WS-DU-RESULT-DATE TO LS-HOLD-RELEASE-DT.
