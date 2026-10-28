"""Generate a minimal synthetic COBOL project during tests; no real upload data."""
from pathlib import Path
import sys
import zipfile


def sample_files() -> dict[str, bytes]:
    return {'README.txt': b'COBOL integration fixture: static CALL, PERFORM, COPY, and a missing dependency.'
                   b'\nThis non-code file should appear in the skipped-file report.\n',
     'copybooks/CUSTOMER.cpy': b'       01 CUSTOMER-RECORD.\n          05 CUSTOMER-ID PIC 9(8).\n      '
                               b'    05 CUSTOMER-ACTIVE PIC X.\n',
     'src/CHECK.cbl': b'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CHECK-CUSTOMER.\n       PR'
                      b"OCEDURE DIVISION.\n       CHECK-LOGIC.\n           DISPLAY 'CUSTOMER CHECKED'\n"
                      b'           GOBACK.\n',
     'src/MAIN.cbl': b'       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MAIN-PROGRAM.\n       DATA'
                     b' DIVISION.\n       WORKING-STORAGE SECTION.\n       COPY CUSTOMER.\n       PROC'
                     b'EDURE DIVISION.\n       MAIN-LOGIC.\n           PERFORM VALIDATE-CUSTOMER\n    '
                     b"       CALL 'CHECK-CUSTOMER'\n           CALL 'MISSING-SERVICE'\n           ST"
                     b"OP RUN.\n       VALIDATE-CUSTOMER.\n           MOVE 'Y' TO CUSTOMER-ACTIVE.\n"}


if __name__ == '__main__':
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in sample_files().items():
            archive.writestr(name, body)
