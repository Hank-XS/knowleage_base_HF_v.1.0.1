      ******************************************************************
      * Program : CBSTM03B
      * Called  : CBSTM03A  (github_cobol/carddemo/CBSTM03A.CBL)
      * Area    : WS-M03B-AREA
      *   DD(8) OPER(1) RC(2) KEY(25) KEY-LN(S9(4)) FLDT(1000)
      * OPER    : O open  C close  R readnext  K readkey  W write  Z rewrite
      * Why     : upstream CardDemo calls this module; it was not in the
      *           downloaded set. Test double that talks to TRNXFILE.
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBSTM03B.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRN-FILE ASSIGN TO TRNXFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS TRN-KEY
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  TRN-FILE.
       01  TRN-REC.
           05  TRN-KEY                 PIC X(25).
           05  TRN-BODY                PIC X(975).
       WORKING-STORAGE SECTION.
       01  WS-FS                       PIC XX VALUE '00'.
       01  WS-OPEN-FLAG                PIC X  VALUE 'N'.
       01  WS-COUNT                    PIC 9(7) VALUE 0.
       01  WS-LAST-OPER                PIC X.
       LINKAGE SECTION.
       01  LS-AREA.
           05  LS-DD                   PIC X(08).
           05  LS-OPER                 PIC X(01).
           05  LS-RC                   PIC X(02).
           05  LS-KEY                  PIC X(25).
           05  LS-KEY-LN               PIC S9(4) COMP.
           05  LS-FLDT                 PIC X(1000).
       PROCEDURE DIVISION USING LS-AREA.
       MAIN.
           MOVE '00' TO LS-RC
           MOVE LS-OPER TO WS-LAST-OPER
           EVALUATE LS-OPER
              WHEN 'O' PERFORM DO-OPEN
              WHEN 'C' PERFORM DO-CLOSE
              WHEN 'R' PERFORM DO-READ-NEXT
              WHEN 'K' PERFORM DO-READ-KEY
              WHEN 'W' PERFORM DO-WRITE
              WHEN 'Z' PERFORM DO-REWRITE
              WHEN OTHER
                 MOVE '99' TO LS-RC
           END-EVALUATE
           GOBACK.

       DO-OPEN.
           IF WS-OPEN-FLAG = 'Y'
              MOVE '04' TO LS-RC
              GO TO DO-OPEN-EXIT
           END-IF
           OPEN I-O TRN-FILE
           IF WS-FS = '00' OR WS-FS = '05'
              MOVE 'Y' TO WS-OPEN-FLAG
              MOVE '00' TO LS-RC
           ELSE
              IF WS-FS = '35'
                 OPEN OUTPUT TRN-FILE
                 CLOSE TRN-FILE
                 OPEN I-O TRN-FILE
                 MOVE 'Y' TO WS-OPEN-FLAG
                 MOVE '00' TO LS-RC
              ELSE
                 MOVE WS-FS TO LS-RC
              END-IF
           END-IF
           .
       DO-OPEN-EXIT.
           EXIT.

       DO-CLOSE.
           IF WS-OPEN-FLAG = 'N'
              MOVE '42' TO LS-RC
           ELSE
              CLOSE TRN-FILE
              MOVE 'N' TO WS-OPEN-FLAG
              MOVE WS-FS TO LS-RC
           END-IF.

       DO-READ-NEXT.
           IF WS-OPEN-FLAG = 'N'
              MOVE '47' TO LS-RC
           ELSE
              READ TRN-FILE NEXT
                 AT END MOVE '10' TO LS-RC
                 NOT AT END
                    MOVE TRN-KEY TO LS-KEY
                    MOVE TRN-REC TO LS-FLDT
                    ADD 1 TO WS-COUNT
                    MOVE '00' TO LS-RC
              END-READ
           END-IF.

       DO-READ-KEY.
           IF WS-OPEN-FLAG = 'N'
              MOVE '47' TO LS-RC
           ELSE
              MOVE LS-KEY TO TRN-KEY
              READ TRN-FILE
                 INVALID KEY MOVE '23' TO LS-RC
                 NOT INVALID KEY
                    MOVE TRN-REC TO LS-FLDT
                    MOVE '00' TO LS-RC
              END-READ
           END-IF.

       DO-WRITE.
           IF WS-OPEN-FLAG = 'N'
              MOVE '48' TO LS-RC
           ELSE
              MOVE LS-FLDT TO TRN-REC
              IF LS-KEY NOT = SPACES
                 MOVE LS-KEY TO TRN-KEY
              END-IF
              WRITE TRN-REC
                 INVALID KEY MOVE '22' TO LS-RC
                 NOT INVALID KEY MOVE '00' TO LS-RC
              END-WRITE
           END-IF.

       DO-REWRITE.
           IF WS-OPEN-FLAG = 'N'
              MOVE '48' TO LS-RC
           ELSE
              MOVE LS-KEY TO TRN-KEY
              READ TRN-FILE
                 INVALID KEY MOVE '23' TO LS-RC
                 NOT INVALID KEY
                    MOVE LS-FLDT TO TRN-REC
                    MOVE LS-KEY TO TRN-KEY
                    REWRITE TRN-REC
                       INVALID KEY MOVE '22' TO LS-RC
                       NOT INVALID KEY MOVE '00' TO LS-RC
                    END-REWRITE
              END-READ
           END-IF.
       END PROGRAM CBSTM03B.
