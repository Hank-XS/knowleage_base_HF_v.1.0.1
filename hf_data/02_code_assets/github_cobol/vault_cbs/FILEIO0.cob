IDENTIFICATION DIVISION.
PROGRAM-ID. FILEIO0.
*> ================================================================
*> FILEIO0 - Indexed File I/O Gateway
*> Provides unified CRUD for all persistent indexed files:
*> ACCT, CIF, TXN, GL, HOLD, AUDT
*> ================================================================

ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT ACCT-FILE ASSIGN TO "data/accounts.dat"
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS AF-ACCT-NUMBER
        FILE STATUS IS WS-ACCT-STATUS.
    SELECT CIF-FILE ASSIGN TO "data/customers.dat"
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS CF-CUST-ID
        FILE STATUS IS WS-CIF-STATUS.
    SELECT TXN-FILE ASSIGN TO "data/transactions.dat"
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS TF-TXN-KEY
        FILE STATUS IS WS-TXN-STATUS.
    SELECT GL-FILE ASSIGN TO "data/gl-entries.dat"
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS GF-GL-KEY
        FILE STATUS IS WS-GL-STATUS.
    SELECT HOLD-FILE ASSIGN TO "data/holds.dat"
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS HF-HOLD-KEY
        FILE STATUS IS WS-HOLD-STATUS.
    SELECT AUDIT-FILE ASSIGN TO "data/audit.dat"
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS XF-AUDIT-KEY
        FILE STATUS IS WS-AUDIT-STATUS.

DATA DIVISION.
FILE SECTION.
FD  ACCT-FILE.
01  AF-ACCT-REC.
    05  AF-ACCT-NUMBER           PIC 9(12).
    05  AF-ACCT-DATA             PIC X(500).

FD  CIF-FILE.
01  CF-CIF-REC.
    05  CF-CUST-ID               PIC 9(10).
    05  CF-CIF-DATA              PIC X(500).

FD  TXN-FILE.
01  TF-TXN-REC.
    05  TF-TXN-KEY.
        10  TF-TXN-ID           PIC 9(15).
        10  TF-TXN-SEQ          PIC 9(5).
    05  TF-TXN-DATA             PIC X(500).

FD  GL-FILE.
01  GF-GL-REC.
    05  GF-GL-KEY.
        10  GF-GL-ACCT-NUM      PIC 9(10).
        10  GF-GL-COST-CTR      PIC 9(4).
    05  GF-GL-DATA              PIC X(300).

FD  HOLD-FILE.
01  HF-HOLD-REC.
    05  HF-HOLD-KEY.
        10  HF-HOLD-ACCT        PIC 9(12).
        10  HF-HOLD-SEQ         PIC 9(5).
    05  HF-HOLD-DATA            PIC X(200).

FD  AUDIT-FILE.
01  XF-AUDIT-REC.
    05  XF-AUDIT-KEY.
        10  XF-AUDIT-ID         PIC 9(15).
        10  XF-AUDIT-SEQ        PIC 9(5).
    05  XF-AUDIT-DATA           PIC X(300).

WORKING-STORAGE SECTION.
01  WS-ACCT-STATUS              PIC X(2).
01  WS-CIF-STATUS               PIC X(2).
01  WS-TXN-STATUS               PIC X(2).
01  WS-GL-STATUS                PIC X(2).
01  WS-HOLD-STATUS              PIC X(2).
01  WS-AUDIT-STATUS             PIC X(2).
01  WS-FILE-OP-STATUS           PIC X(2).

LINKAGE SECTION.
COPY CPYFIO.
01  LS-RECORD-AREA              PIC X(512).

PROCEDURE DIVISION USING LS-FILE-REQUEST
                         LS-RECORD-AREA
                         LS-FILE-RESULT.
MAIN-LOGIC.
    MOVE "00" TO LS-FIO-STATUS
    MOVE "E0000" TO LS-FIO-RESULT-CODE
    MOVE SPACES TO LS-FIO-RESULT-MSG

    EVALUATE LS-FIO-FUNCTION
        WHEN "OPEN"
            PERFORM DO-OPEN
        WHEN "CLOS"
            PERFORM DO-CLOSE
        WHEN "READ"
            PERFORM DO-READ
        WHEN "WRIT"
            PERFORM DO-WRITE
        WHEN "REWT"
            PERFORM DO-REWRITE
        WHEN "DELT"
            PERFORM DO-DELETE
        WHEN "NEXT"
            PERFORM DO-READ-NEXT
        WHEN "STRT"
            PERFORM DO-START
        WHEN OTHER
            MOVE "99" TO LS-FIO-STATUS
            MOVE "E0001" TO LS-FIO-RESULT-CODE
            MOVE "Invalid file I/O function" TO LS-FIO-RESULT-MSG
    END-EVALUATE
    GOBACK.

*> ---------------------------------------------------------------
*> OPEN - Open indexed file for I-O (create if not exists)
*> ---------------------------------------------------------------
DO-OPEN.
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            OPEN I-O ACCT-FILE
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
            IF WS-ACCT-STATUS = "35"
                OPEN OUTPUT ACCT-FILE
                CLOSE ACCT-FILE
                OPEN I-O ACCT-FILE
                MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
            END-IF
        WHEN "CIF "
            OPEN I-O CIF-FILE
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
            IF WS-CIF-STATUS = "35"
                OPEN OUTPUT CIF-FILE
                CLOSE CIF-FILE
                OPEN I-O CIF-FILE
                MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
            END-IF
        WHEN "TXN "
            OPEN I-O TXN-FILE
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
            IF WS-TXN-STATUS = "35"
                OPEN OUTPUT TXN-FILE
                CLOSE TXN-FILE
                OPEN I-O TXN-FILE
                MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
            END-IF
        WHEN "GL  "
            OPEN I-O GL-FILE
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
            IF WS-GL-STATUS = "35"
                OPEN OUTPUT GL-FILE
                CLOSE GL-FILE
                OPEN I-O GL-FILE
                MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
            END-IF
        WHEN "HOLD"
            OPEN I-O HOLD-FILE
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
            IF WS-HOLD-STATUS = "35"
                OPEN OUTPUT HOLD-FILE
                CLOSE HOLD-FILE
                OPEN I-O HOLD-FILE
                MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
            END-IF
        WHEN "AUDT"
            OPEN I-O AUDIT-FILE
            MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
            IF WS-AUDIT-STATUS = "35"
                OPEN OUTPUT AUDIT-FILE
                CLOSE AUDIT-FILE
                OPEN I-O AUDIT-FILE
                MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
            END-IF
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> CLOSE - Close indexed file
*> ---------------------------------------------------------------
DO-CLOSE.
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            CLOSE ACCT-FILE
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            CLOSE CIF-FILE
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            CLOSE TXN-FILE
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            CLOSE GL-FILE
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            CLOSE HOLD-FILE
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN "AUDT"
            CLOSE AUDIT-FILE
            MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> READ - Read record by key
*> ---------------------------------------------------------------
DO-READ.
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            MOVE LS-FIO-KEY(1:12) TO AF-ACCT-NUMBER
            READ ACCT-FILE INTO LS-RECORD-AREA
                KEY IS AF-ACCT-NUMBER
            END-READ
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            MOVE LS-FIO-KEY(1:10) TO CF-CUST-ID
            READ CIF-FILE INTO LS-RECORD-AREA
                KEY IS CF-CUST-ID
            END-READ
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            MOVE LS-FIO-KEY(1:15) TO TF-TXN-ID
            MOVE LS-FIO-KEY(16:5) TO TF-TXN-SEQ
            READ TXN-FILE INTO LS-RECORD-AREA
                KEY IS TF-TXN-KEY
            END-READ
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            MOVE LS-FIO-KEY(1:10) TO GF-GL-ACCT-NUM
            MOVE LS-FIO-KEY(11:4) TO GF-GL-COST-CTR
            READ GL-FILE INTO LS-RECORD-AREA
                KEY IS GF-GL-KEY
            END-READ
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            MOVE LS-FIO-KEY(1:12) TO HF-HOLD-ACCT
            MOVE LS-FIO-KEY(13:5) TO HF-HOLD-SEQ
            READ HOLD-FILE INTO LS-RECORD-AREA
                KEY IS HF-HOLD-KEY
            END-READ
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN "AUDT"
            MOVE LS-FIO-KEY(1:15) TO XF-AUDIT-ID
            MOVE LS-FIO-KEY(16:5) TO XF-AUDIT-SEQ
            READ AUDIT-FILE INTO LS-RECORD-AREA
                KEY IS XF-AUDIT-KEY
            END-READ
            MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> WRITE - Write new record
*> ---------------------------------------------------------------
DO-WRITE.
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            WRITE AF-ACCT-REC FROM LS-RECORD-AREA
            END-WRITE
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            WRITE CF-CIF-REC FROM LS-RECORD-AREA
            END-WRITE
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            WRITE TF-TXN-REC FROM LS-RECORD-AREA
            END-WRITE
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            WRITE GF-GL-REC FROM LS-RECORD-AREA
            END-WRITE
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            WRITE HF-HOLD-REC FROM LS-RECORD-AREA
            END-WRITE
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN "AUDT"
            WRITE XF-AUDIT-REC FROM LS-RECORD-AREA
            END-WRITE
            MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> REWRITE - Update existing record
*> ---------------------------------------------------------------
DO-REWRITE.
    IF LS-FIO-FILE-ID = "AUDT"
        MOVE "99" TO LS-FIO-STATUS
        MOVE "E0005" TO LS-FIO-RESULT-CODE
        MOVE "Audit records are immutable" TO LS-FIO-RESULT-MSG
        EXIT PARAGRAPH
    END-IF
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            REWRITE AF-ACCT-REC FROM LS-RECORD-AREA
            END-REWRITE
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            REWRITE CF-CIF-REC FROM LS-RECORD-AREA
            END-REWRITE
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            REWRITE TF-TXN-REC FROM LS-RECORD-AREA
            END-REWRITE
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            REWRITE GF-GL-REC FROM LS-RECORD-AREA
            END-REWRITE
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            REWRITE HF-HOLD-REC FROM LS-RECORD-AREA
            END-REWRITE
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> DELETE - Delete record by key
*> ---------------------------------------------------------------
DO-DELETE.
    IF LS-FIO-FILE-ID = "AUDT"
        MOVE "99" TO LS-FIO-STATUS
        MOVE "E0005" TO LS-FIO-RESULT-CODE
        MOVE "Audit records are immutable" TO LS-FIO-RESULT-MSG
        EXIT PARAGRAPH
    END-IF
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            DELETE ACCT-FILE
            END-DELETE
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            DELETE CIF-FILE
            END-DELETE
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            DELETE TXN-FILE
            END-DELETE
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            DELETE GL-FILE
            END-DELETE
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            DELETE HOLD-FILE
            END-DELETE
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> READ-NEXT - Sequential read (after START or previous READ NEXT)
*> ---------------------------------------------------------------
DO-READ-NEXT.
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            READ ACCT-FILE NEXT INTO LS-RECORD-AREA
            END-READ
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            READ CIF-FILE NEXT INTO LS-RECORD-AREA
            END-READ
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            READ TXN-FILE NEXT INTO LS-RECORD-AREA
            END-READ
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            READ GL-FILE NEXT INTO LS-RECORD-AREA
            END-READ
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            READ HOLD-FILE NEXT INTO LS-RECORD-AREA
            END-READ
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN "AUDT"
            READ AUDIT-FILE NEXT INTO LS-RECORD-AREA
            END-READ
            MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> START - Position for sequential browse
*> ---------------------------------------------------------------
DO-START.
    EVALUATE LS-FIO-FILE-ID
        WHEN "ACCT"
            MOVE LS-FIO-KEY(1:12) TO AF-ACCT-NUMBER
            START ACCT-FILE KEY >= AF-ACCT-NUMBER
            END-START
            MOVE WS-ACCT-STATUS TO WS-FILE-OP-STATUS
        WHEN "CIF "
            MOVE LS-FIO-KEY(1:10) TO CF-CUST-ID
            START CIF-FILE KEY >= CF-CUST-ID
            END-START
            MOVE WS-CIF-STATUS TO WS-FILE-OP-STATUS
        WHEN "TXN "
            MOVE LS-FIO-KEY(1:15) TO TF-TXN-ID
            MOVE LS-FIO-KEY(16:5) TO TF-TXN-SEQ
            START TXN-FILE KEY >= TF-TXN-KEY
            END-START
            MOVE WS-TXN-STATUS TO WS-FILE-OP-STATUS
        WHEN "GL  "
            MOVE LS-FIO-KEY(1:10) TO GF-GL-ACCT-NUM
            MOVE LS-FIO-KEY(11:4) TO GF-GL-COST-CTR
            START GL-FILE KEY >= GF-GL-KEY
            END-START
            MOVE WS-GL-STATUS TO WS-FILE-OP-STATUS
        WHEN "HOLD"
            MOVE LS-FIO-KEY(1:12) TO HF-HOLD-ACCT
            MOVE LS-FIO-KEY(13:5) TO HF-HOLD-SEQ
            START HOLD-FILE KEY >= HF-HOLD-KEY
            END-START
            MOVE WS-HOLD-STATUS TO WS-FILE-OP-STATUS
        WHEN "AUDT"
            MOVE LS-FIO-KEY(1:15) TO XF-AUDIT-ID
            MOVE LS-FIO-KEY(16:5) TO XF-AUDIT-SEQ
            START AUDIT-FILE KEY >= XF-AUDIT-KEY
            END-START
            MOVE WS-AUDIT-STATUS TO WS-FILE-OP-STATUS
        WHEN OTHER
            MOVE "99" TO WS-FILE-OP-STATUS
    END-EVALUATE
    PERFORM CHECK-FILE-STATUS.

*> ---------------------------------------------------------------
*> Check file status and set result codes
*> ---------------------------------------------------------------
CHECK-FILE-STATUS.
    MOVE WS-FILE-OP-STATUS TO LS-FIO-STATUS
    EVALUATE WS-FILE-OP-STATUS
        WHEN "00"
            MOVE "E0000" TO LS-FIO-RESULT-CODE
            MOVE SPACES TO LS-FIO-RESULT-MSG
        WHEN "02"
            *> Duplicate alternate key (OK for write)
            MOVE "E0000" TO LS-FIO-RESULT-CODE
            MOVE SPACES TO LS-FIO-RESULT-MSG
        WHEN "10"
            *> End of file
            MOVE "10" TO LS-FIO-STATUS
            MOVE "E0004" TO LS-FIO-RESULT-CODE
            MOVE "End of file reached" TO LS-FIO-RESULT-MSG
        WHEN "22"
            *> Duplicate key on write
            MOVE "E0005" TO LS-FIO-RESULT-CODE
            MOVE "Duplicate record key" TO LS-FIO-RESULT-MSG
        WHEN "23"
            *> Record not found
            MOVE "E0004" TO LS-FIO-RESULT-CODE
            MOVE "Record not found" TO LS-FIO-RESULT-MSG
        WHEN "35"
            *> File not found (open)
            MOVE "E0003" TO LS-FIO-RESULT-CODE
            MOVE "File not found" TO LS-FIO-RESULT-MSG
        WHEN OTHER
            MOVE "E0003" TO LS-FIO-RESULT-CODE
            STRING "File I/O error: " WS-FILE-OP-STATUS
                DELIMITED BY SIZE INTO LS-FIO-RESULT-MSG
            END-STRING
    END-EVALUATE.
