"""同步 DEFAULT_VOCAB → DB，并审计图谱 Tag 是否全部落在词表内。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(__file__).rsplit("scripts", 1)[0].rstrip("\\/"))

from app.ingest.tagger import sync_vocab_defaults  # noqa: E402
from scripts.audit_tags_vs_vocab import main as audit_main  # noqa: E402


if __name__ == "__main__":
    r = sync_vocab_defaults()
    print("sync_vocab_defaults:", r)
    print()
    audit_main()
