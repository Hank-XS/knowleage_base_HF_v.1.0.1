      *****************************************************************
      * COPYBOOK: PYTXNCA  - Payment Transaction COMMAREA             *
      * USED BY : PYMAIN / PYVAL / PYROUTE / PYPOST / PYMSGOT         *
      *****************************************************************
       01  PY-TXN-COMMAREA.
           05  PY-CA-VERSION         PIC X(04) VALUE 'V321'.
           05  PY-CA-TXN-ID          PIC X(17).
           05  PY-CA-UETR            PIC X(36).
           05  PY-CA-MSG-TYPE        PIC X(10).
           05  PY-CA-SRC-SYS         PIC X(08).
           05  PY-CA-PRIORITY        PIC 9(01).
           05  PY-CA-AMOUNT          PIC S9(13)V99 COMP-3.
           05  PY-CA-CURRENCY        PIC X(03).
           05  PY-CA-VALUE-DATE      PIC X(10).
           05  PY-CA-DEBTOR-ACCT     PIC X(34).
           05  PY-CA-CREDITOR-ACCT   PIC X(34).
           05  PY-CA-SENDER-BIC      PIC X(11).
           05  PY-CA-RECEIVER-BIC    PIC X(11).
           05  PY-CA-REMIT-INFO      PIC X(140).
           05  PY-CA-ROUTE-CHNL      PIC X(10).
           05  PY-CA-AML-RESULT      PIC X(08).
           05  PY-CA-AML-SCORE       PIC S9(05) COMP-3.
           05  PY-CA-STATUS          PIC X(10).
           05  PY-CA-REASON-CD       PIC X(10).
           05  PY-CA-RETRY-CNT       PIC 9(02).
           05  PY-CA-RC              PIC S9(04) COMP.
           05  PY-CA-SQLCODE         PIC S9(09) COMP.
           05  PY-CA-FLAGS.
               10  PY-CA-FLG-IDEMP   PIC X VALUE 'N'.
               10  PY-CA-FLG-FX      PIC X VALUE 'N'.
               10  PY-CA-FLG-HOLD    PIC X VALUE 'N'.
               10  PY-CA-FLG-REPLAY  PIC X VALUE 'N'.
           05  PY-CA-AUDIT-TS        PIC X(26).
           05  PY-CA-FILLER          PIC X(64).
