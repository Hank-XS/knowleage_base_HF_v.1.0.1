**FREE
// RPTCARD - statement companion for CBSTM03A output
// Reads the same card/account idea as COACTVWC / COTRN00C
// and flags accounts whose statement job abended (CEE3ABD).
ctl-opt dftactgrp(*no) option(*srcstmt);

dcl-f CARDACCT disk(*ext) usage(*input) keyed;
dcl-f QSYSPRT printer(132);

dcl-s nAcct int(10);
dcl-s nNeg  int(10);
dcl-s tot   packed(15:2);
dcl-s line  char(132);

setll *loval CARDACCT;
read CARDACCT;
dow not %eof(CARDACCT);
  nAcct += 1;
  tot += CURRBAL;
  if CURRBAL < 0;
    nNeg += 1;
  endif;
  read CARDACCT;
enddo;

line = 'CARD STATEMENT CONTROL  accts=' + %char(nAcct)
     + ' neg=' + %char(nNeg)
     + ' bal=' + %char(tot);
except detail;
if nNeg > 0;
  line = 'see COBIL00C CB00 for payoff; batch is CBSTM03A';
  except detail;
endif;
*inlr = *on;
return;
