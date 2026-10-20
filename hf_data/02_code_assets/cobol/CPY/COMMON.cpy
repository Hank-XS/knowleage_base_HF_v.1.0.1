      *****************************************************************
      * COMMON.cpy - the cursed shared copybook                       *
      * EVERY program copy this. change one field = weekend            *
      * 1998 created. 47 people edited. no owner.                      *
      *****************************************************************
       01  COM-AREA.
           05  COM-TXN-ID        PIC X(12).
      *    05  COM-TXN-ID        PIC X(17).  *> extended 2016 half migrate
           05  COM-TXN-ID-NEW    PIC X(17).
           05  COM-AMT           PIC 9(11)V99.
           05  COM-AMT-NEW       PIC S9(13)V99 COMP-3.
           05  COM-CCY           PIC X(03).
           05  COM-CCY-OLD       PIC XX.
           05  COM-STATUS        PIC X.
      *    0=init 1=ok 2=err 3=??? 4=hold 5=settled 9=dont use
           05  COM-STATUS-NEW    PIC X(10).
           05  COM-FLAG1         PIC X.
           05  COM-FLAG2         PIC X.
           05  COM-FLAG3         PIC X.
           05  COM-FLAG4         PIC X.
           05  COM-FLAG5         PIC X.
           05  COM-TEMP          PIC X(100).
           05  COM-TEMP2         PIC X(100).
           05  COM-TEMP3         PIC X(100).
           05  COM-USER          PIC X(8).
           05  COM-USER2         PIC X(20).
           05  COM-DATE          PIC 9(8).
           05  COM-DATE-ISO      PIC X(10).
           05  COM-FILLER        PIC X(200).
           05  COM-FILLER2       PIC X(200).
      *    REDEFINES war zone
           05  COM-AMT-X REDEFINES COM-AMT PIC X(13).
           05  COM-FLAGS REDEFINES COM-FLAG1.
               10  COM-F1 PIC X.
               10  COM-F2 PIC X.
               10  COM-F3 PIC X.
               10  COM-F4 PIC X.
               10  COM-F5 PIC X.
      *    wait COM-FLAG2 etc also exist separately - overlap undefined

       01  COM-CONST.
           05  COM-OK            PIC X VALUE '1'.
           05  COM-ERR           PIC X VALUE '2'.
           05  COM-MAX-RETRY     PIC 9 VALUE 3.
           05  COM-MAX-RETRY2    PIC 9 VALUE 5.
           05  COM-MAGIC         PIC 9(4) VALUE 9999.
           05  COM-BANK-BIC      PIC X(11) VALUE 'HSBCHKHHXXX'.
           05  COM-TEST-MODE     PIC X VALUE 'N'.
      *    COM-TEST-MODE left Y in PROD 3 days 2014

       88  COM-IS-OK             VALUE '1' 'Y' 'y' 'OK' 'ok'.
      * 88 on COM-AREA? no on COM-STATUS - but people use wrong parent
