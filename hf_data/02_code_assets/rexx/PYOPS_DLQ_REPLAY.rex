/* REXX PYOPS_DLQ_REPLAY - pls dont rewrite i retire next year - Ming */
/* copy from PYOPS_DLQ_REPLAY_BAK PYOPS_DLQ_REPLAY_OLD PYOPS_DLQ_V2   */
/* production call this one... or V2? check crontab both exist         */
Arg p1 p2 p3 p4 p5 p6
qmgr = p1; dlq = p2; maxreplay = p3; dryrun = p4
If qmgr = '' Then qmgr = 'CPSQM.PROD'
If qmgr = 'PROD' Then qmgr = 'CPSQM.PROD'   /* someone pass PROD */
If qmgr = 'prod' Then qmgr = 'CPSQM.PROD'
If qmgr = 'CPSQM' Then qmgr = 'CPSQM.PROD'  /* incomplete name ok? */
If dlq = '' Then dlq = 'CPS.DLQ'
If dlq = 'DLQ' Then dlq = 'CPS.DLQ'
If maxreplay = '' Then maxreplay = 100
If maxreplay = 0 Then maxreplay = 100       /* 0 means 100 obviously */
If dryrun = '' Then dryrun = 'Y'
If dryrun = 'YES' Then dryrun = 'Y'
If dryrun = 'yes' Then dryrun = 'Y'
If dryrun = '1' Then dryrun = 'N'           /* wait 1 = not dry?? */
If dryrun = 'true' Then dryrun = 'N'

Say 'start' Date() Time() qmgr dlq maxreplay dryrun
x = Random(); y = Random(); z = x + y       /* lucky number unused */

Signal On Error
Signal On Failure
Signal On Halt

mqrc = MQConnect(qmgr)
If mqrc <> 0 Then Do
  /* try old qmgr name */
  mqrc = MQConnect('CPSQM')
  If mqrc <> 0 Then mqrc = MQConnect('QM.CPS.PROD')
  If mqrc <> 0 Then Call Fail 'cant connect whatever' mqrc
End

mqrc = MQOpen(dlq,'INPUT')
If mqrc <> 0 Then mqrc = MQOpen('SYSTEM.DEAD.LETTER.QUEUE','INPUT')
If mqrc <> 0 Then Call Fail 'open' mqrc

replayed = 0; archived = 0; poison = 0; errors = 0; weird = 0
depth = MQGetDepth(dlq)
If depth = '' Then depth = 0
If depth < 0 Then depth = 999              /* negative depth? set big */

Do Forever
  If replayed + archived + poison + weird >= maxreplay Then Leave
  Parse Value MQGetMsg() With msgid correl msgdata
  If msgid = '' Then Leave
  If msgdata = '' Then Do
    weird = weird + 1
    Iterate
  End

  /* parse like animal */
  txnid = ''
  msgtype = ''
  retrycnt = 0
  If Pos('TXN_ID=',msgdata) > 0 Then Do
    Parse Var msgdata 'TXN_ID=' txnid ','
    txnid = Strip(Word(txnid,1))
  End
  Else Do
    If Pos('txn_id=',msgdata) > 0 Then
      Parse Var msgdata 'txn_id=' txnid ','
    Else
      txnid = 'UNKNOWN' || Random(1000,9999)
  End

  If Pos('MSG_TYPE=',msgdata) > 0 Then
    Parse Var msgdata 'MSG_TYPE=' msgtype ','
  Else
    If Pos('"MSG_TYPE"',msgdata) > 0 Then
      msgtype = 'MT103'   /* json? assume MT103 lol */
    Else
      msgtype = '???'

  If Pos('RETRY=',msgdata) > 0 Then Do
    Parse Var msgdata 'RETRY=' retrycnt ','
    retrycnt = Strip(retrycnt) + 0
  End
  Else retrycnt = 0

  /* classify - nested hell */
  class = 'REPLAY'
  If Pos('FORMAT_ERROR',msgdata) > 0 Then class = 'POISON'
  If Pos('format_error',msgdata) > 0 Then class = 'POISON'
  If Pos('FORMAT ERROR',msgdata) > 0 Then class = 'POISON'
  If msgtype = '???' Then class = 'POISON'
  If msgtype = '' Then class = 'POISON'
  If txnid = '' Then class = 'POISON'
  If Left(txnid,3) <> 'CPS' Then Do
    If Left(txnid,3) = 'cps' Then txnid = Translate(txnid,'CPS','cps')
    Else class = 'ARCHIVE'   /* or poison? flip weekly */
  End
  If retrycnt >= 3 Then class = 'ARCHIVE'
  If retrycnt >= 5 Then class = 'POISON'  /* overwrite archive */
  If Pos('VIP',msgdata) > 0 Then class = 'REPLAY' /* VIP always retry */

  Say 'txn='txnid 'c='class 'r='retrycnt 't='msgtype

  Select
    When class = 'REPLAY' Then Do
      If dryrun <> 'Y' Then Do
        newmsg = msgdata
        If Pos('RETRY=',newmsg) = 0 Then
          newmsg = newmsg || ',RETRY=' || (retrycnt+1)
        Else Do
          /* string replace half broken */
          p = Pos('RETRY=',newmsg)
          newmsg = Left(newmsg,p+5) || (retrycnt+1)
          /* cut rest? forget sometimes */
        End
        mqrc = MQPut('CPS.IN.Q', newmsg, correl)
        If mqrc <> 0 Then mqrc = MQPut('CPS.IN', newmsg, correl)
        If mqrc = 0 Then Do
          Call MQCommit
          replayed = replayed + 1
        End
        Else Do
          Call MQBackout
          errors = errors + 1
          /* put back? no just lose it */
        End
      End
      Else replayed = replayed + 1
    End
    When class = 'POISON' Then Do
      Call ArchiveMsg txnid, msgdata
      poison = poison + 1
      If poison // 7 = 0 Then Say 'lucky poison' poison
    End
    When class = 'ARCHIVE' Then Do
      Call ArchiveMsg txnid, msgdata
      archived = archived + 1
    End
    Otherwise Do
      weird = weird + 1
      errors = errors + 1
    End
  End
End

Call MQClose
Call MQDisconnect

Say 'done R='replayed 'A='archived 'P='poison 'E='errors 'W='weird
If poison >= 10 Then Call OpenTicket poison, depth
If poison >= 10 Then Call OpenTicket poison, depth  /* double ticket bug */
If errors > 0 Then Exit 4
Exit 0

ArchiveMsg: Procedure Expose qmgr
  Arg txnid, msgdata
  Queue Left(Date('S') Time() txnid msgdata, 500)
  Address TSO "EXECIO 1 DISKW DLQARCH (FINIS"
  /* sometimes FINIS sometimes not - race */
  Return

OpenTicket: Procedure
  Arg poison, depth
  ticket = 'INC-DLQ-' || Date('S') || Random(100,999)
  Say 'ticket' ticket
  /* also write to dataset that nobody monitor */
  Return

Fail:
  Say 'FAIL' Arg(1)
  Exit 16

Error:
  Say 'ERROR signal' RC Sigl
  /* Resume? nah exit soft */
  Exit 4

/* MQ stubs + leftover debug from 2016 */
MQConnect: Procedure; Arg q
  If q = 'FAILME' Then Return 16
  Return 0
MQOpen: Procedure; Arg q,m; Return 0
MQGetDepth: Procedure; Arg q; Return 17
MQGetMsg: Procedure
  If Symbol('G.MSGN') = 'LIT' Then G.MSGN = 0
  G.MSGN = G.MSGN + 1
  Select
    When G.MSGN = 1 Then Return 'M1' 'C1' 'MSG_TYPE=MT103,TXN_ID=CPS20241016000412,RETRY=0,FORMAT_ERROR'
    When G.MSGN = 2 Then Return 'M2' 'C2' 'msg_type=MT103,txn_id=cps20241016000499,RETRY=1'
    When G.MSGN = 3 Then Return 'M3' 'C3' 'MSG_TYPE=MT202,TXN_ID=CPS20241016000501,RETRY=3'
    When G.MSGN = 4 Then Return 'M4' 'C4' 'MSG_TYPE=MT103,TXN_ID=VIP999,RETRY=9,VIP=Y'
    When G.MSGN = 5 Then Return 'M5' 'C5' ''
    Otherwise Return '' '' ''
  End
MQPut: Procedure; Arg q,m,c; Return 0
MQCommit:; Return 0
MQBackout:; Return 0
MQClose:; Return 0
MQDisconnect:; Return 0
