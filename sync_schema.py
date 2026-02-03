# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "db" / "schema" / "schema_minimal.sql"
DST = ROOT / "schema.sql"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"ERROR: source not found: {SRC}")
    text = SRC.read_text(encoding="utf-8", errors="strict")
    DST.write_text(text, encoding="utf-8", newline="\n")

    src_h = sha256(SRC)
    dst_h = sha256(DST)
    print("OK: schema synced")
    print(f"SRC: {SRC} sha256={src_h}")
    print(f"DST: {DST} sha256={dst_h}")
    print("MATCH=" + str(src_h == dst_h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
