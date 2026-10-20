      *****************************************************************
      * COPYBOOK: PYERRCDS - CPS Standard Return / Reason Codes       *
      *****************************************************************
       01  PY-ERR-CODES.
           05  PY-RC-OK              PIC S9(04) COMP VALUE +0.
           05  PY-RC-WARN            PIC S9(04) COMP VALUE +4.
           05  PY-RC-RETRY           PIC S9(04) COMP VALUE +8.
           05  PY-RC-REJECT          PIC S9(04) COMP VALUE +12.
           05  PY-RC-FATAL           PIC S9(04) COMP VALUE +16.
       01  PY-REASON-TABLE.
           05  FILLER PIC X(20) VALUE 'VAL001  IBAN_CHK    '.
           05  FILLER PIC X(20) VALUE 'VAL002  CCY_WHITE   '.
           05  FILLER PIC X(20) VALUE 'VAL003  AMT_POS     '.
           05  FILLER PIC X(20) VALUE 'VAL004  BIC_FMT     '.
           05  FILLER PIC X(20) VALUE 'VAL005  VDATE_BD    '.
           05  FILLER PIC X(20) VALUE 'AML001  SANCTION_HIT'.
           05  FILLER PIC X(20) VALUE 'AML002  AML_TIMEOUT '.
           05  FILLER PIC X(20) VALUE 'AML003  AML_SUSPECT '.
           05  FILLER PIC X(20) VALUE 'RTE001  NOSTRO_LOW  '.
           05  FILLER PIC X(20) VALUE 'RTE002  CHNL_DOWN   '.
           05  FILLER PIC X(20) VALUE 'PST001  DB2_DEADLOCK'.
           05  FILLER PIC X(20) VALUE 'PST002  IDEMP_DUP   '.
           05  FILLER PIC X(20) VALUE 'PST003  GLS_REJECT  '.
           05  FILLER PIC X(20) VALUE 'MQE001  Q_FULL      '.
           05  FILLER PIC X(20) VALUE 'MQE002  FMT_ERROR   '.
       01  PY-REASON-ENTRIES REDEFINES PY-REASON-TABLE.
           05  PY-REASON-ENT OCCURS 15 TIMES.
               10  PY-RSN-CODE       PIC X(08).
               10  PY-RSN-DESC       PIC X(12).
