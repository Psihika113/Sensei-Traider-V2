# -*- coding: utf-8 -*-
"""
fix_executions_cleanup.py

Чистит мусор в таблице executions для заданного order_id:
- удаляет leg='CLOSE'
- оставляет только самый ранний PARENT как entry
- удаляет ошибочные PARENT на SELL-таймстемпах (если на том же ts/price/qty есть TAKE/STOP)
- убирает дубли по ключу (leg, ts_utc, price, qty)

По умолчанию DRY RUN (ничего не удаляет).
Для применения: --apply

Пример:
  call .\.venv\Scripts\activate
  python fix_executions_cleanup.py --db data\\trader_paper.db --order-id sensei-dd44120cc8 --apply
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict


def fetchall(con, sql, params=()):
    cur = con.cursor()
    return cur.execute(sql, params).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"data\trader_paper.db")
    ap.add_argument("--order-id", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    try:
        cur = con.cursor()

        rows = fetchall(
            con,
            "SELECT id, order_id, leg, ts_utc, price, qty FROM executions WHERE order_id=? ORDER BY id",
            (args.order_id,),
        )
        if not rows:
            print("[cleanup] no executions for order_id:", args.order_id)
            return 0

        print(f"[cleanup] DB={args.db}")
        print(f"[cleanup] order_id={args.order_id}")
        print(f"[cleanup] executions rows={len(rows)}")
        for r in rows:
            print("  ", r)

        ids_to_delete = set()

        # 1) delete CLOSE legs (ручные вставки ломают знак qty/логику)
        for (rid, oid, leg, ts, price, qty) in rows:
            if str(leg).upper() == "CLOSE":
                ids_to_delete.add(rid)

        # 2) keep only earliest PARENT as entry
        parent_rows = [(rid, ts, price, qty) for (rid, oid, leg, ts, price, qty) in rows if str(leg).upper() == "PARENT"]
        parent_rows_sorted = sorted(parent_rows, key=lambda x: (x[1], x[0]))  # by ts, id
        keep_parent_id = parent_rows_sorted[0][0] if parent_rows_sorted else None

        for (rid, ts, price, qty) in parent_rows_sorted[1:]:
            ids_to_delete.add(rid)

        # 3) remove "PARENT sells": if on same (ts,price,qty) exists TAKE/STOP, then PARENT is wrong
        # (кроме первого entry PARENT)
        keyed = defaultdict(list)  # (ts,price,abs(qty)) -> [(id, leg, qty)]
        for (rid, oid, leg, ts, price, qty) in rows:
            key = (ts, float(price), float(abs(qty)))
            keyed[key].append((rid, str(leg).upper(), float(qty)))

        for key, items in keyed.items():
            has_take_or_stop = any(l in ("TAKE", "STOP") for (_, l, _) in items)
            if not has_take_or_stop:
                continue

            for (rid, leg_u, qty) in items:
                if leg_u == "PARENT" and rid != keep_parent_id:
                    ids_to_delete.add(rid)

        # 4) dedupe by (leg, ts, price, qty): keep smallest id
        seen = {}
        for (rid, oid, leg, ts, price, qty) in rows:
            leg_u = str(leg).upper()
            k = (leg_u, ts, float(price), float(qty))
            if k not in seen:
                seen[k] = rid
            else:
                ids_to_delete.add(rid)

        ids_to_delete = sorted(ids_to_delete)

        print("\n[cleanup] would delete ids:", ids_to_delete)
        if not ids_to_delete:
            print("[cleanup] nothing to delete.")
            return 0

        if not args.apply:
            print("[cleanup] DRY RUN. Add --apply to execute deletions.")
            return 0

        # apply delete
        cur.executemany("DELETE FROM executions WHERE id=?", [(i,) for i in ids_to_delete])
        con.commit()
        print("[cleanup] deleted:", len(ids_to_delete))

        # show after
        after = fetchall(
            con,
            "SELECT id, order_id, leg, ts_utc, price, qty FROM executions WHERE order_id=? ORDER BY id",
            (args.order_id,),
        )
        print("\n[cleanup] after rows:", len(after))
        for r in after:
            print("  ", r)

        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
