//PYINBPRO PROC ENV=PROD,
//             QMGR=CPSQM.PROD,
//             INQ=CPS.IN.Q,
//             DLQ=CPS.DLQ,
//             LOADLIB=CPS.PROD.LOAD,
//             DB2SSID=DB2P,
//             MAXMSG=5000
//*==================================================================*
//* PROC: Drain inbound MQ, invoke CICS mirror / batch parser,       *
//*       poison-message to DLQ after 3 attempts                      *
//*==================================================================*
//STEP010  EXEC PGM=IKJEFT01,DYNAMNBR=30
//STEPLIB  DD DSN=&LOADLIB,DISP=SHR
//SYSTSIN  DD *
  DSN SYSTEM(&DB2SSID)
  RUN PROGRAM(PYMQDRN) PLAN(CPSPLAN) -
      PARMS('/QMGR=&QMGR/Q=&INQ/DLQ=&DLQ/MAX=&MAXMSG/RETRY=3')
  END
/*
//SYSTSPRT DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//STATOUT  DD SYSOUT=*
//*
//STEP020  EXEC PGM=PYBATIN,COND=(4,LT)
//STEPLIB  DD DSN=&LOADLIB,DISP=SHR
//INFLAT   DD DSN=CPS.&ENV..INBOUND.FLAT,DISP=SHR
//OUTBAD   DD DSN=CPS.&ENV..INBOUND.BAD(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(5,2),RLSE),
//            DCB=(RECFM=VB,LRECL=8196,BLKSIZE=0)
//SYSPRINT DD SYSOUT=*
//         PEND
//*
//*---- Example invocation ----
//* //RUNINB  EXEC PYINBPRO,ENV=PROD,MAXMSG=10000
