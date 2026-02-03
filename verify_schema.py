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
        print(f"FAIL: source not found: {SRC}")
        return 2
    if not DST.exists():
        print(f"FAIL: schema.sql not found: {DST}")
        return 2

    src_h = sha256(SRC)
    dst_h = sha256(DST)

    if src_h != dst_h:
        print("FAIL: schema.sql does not match schema_minimal.sql")
        print(f"SRC: {SRC} sha256={src_h}")
        print(f"DST: {DST} sha256={dst_h}")
        print("HINT: run: python sync_schema.py")
        return 1

    print("OK: schema.sql matches schema_minimal.sql")
    print(f"sha256={src_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
