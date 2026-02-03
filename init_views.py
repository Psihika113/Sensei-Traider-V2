# init_views.py
# ==========================================
# Инициализация служебных объектов для SenseiTrader:
#   1) Добавляем недостающий столбец orders.last_update_ts_utc
#   2) Создаём/обновляем VIEW positions
#   3) Создаём/обновляем VIEW v_order_pnl_r (заглушка)
#
# Запуск:
#   (.venv) python init_views.py

import sqlite3
from pathlib import Path


DB_PATH = Path("data") / "trader.db"


def ensure_orders_last_update_column(conn: sqlite3.Connection) -> None:
    """
    Проверяет, есть ли в таблице orders колонка last_update_ts_utc.
    Если нет — добавляет её.
    """
    cur = conn.execute("PRAGMA table_info(orders);")
    cols = [row[1] for row in cur.fetchall()]  # row[1] = name

    if "last_update_ts_utc" not in cols:
        print("Колонка orders.last_update_ts_utc не найдена — добавляем...")
        conn.execute(
            "ALTER TABLE orders ADD COLUMN last_update_ts_utc TEXT"
        )
    else:
        print("Колонка orders.last_update_ts_utc уже существует.")


def init_positions_view(conn: sqlite3.Connection) -> None:
    """
    Создаёт VIEW positions, агрегирующий executions + orders.

    ВАЖНО: колонка qty — именно так её ожидает risk-модуль.
      - берём только leg = 'PARENT'
      - BUY даёт +qty, SELL даёт -qty
      - группируем по symbol
    """
    sql = """
    CREATE VIEW IF NOT EXISTS positions AS
    SELECT
        o.symbol AS symbol,
        SUM(
            CASE
                WHEN UPPER(o.side) = 'BUY'  THEN e.qty
                WHEN UPPER(o.side) = 'SELL' THEN -e.qty
                ELSE 0
            END
        ) AS qty,
        COUNT(*) AS exec_count,
        COALESCE(SUM(e.fee), 0.0) AS total_fee
    FROM executions e
    JOIN orders o
        ON e.order_id = o.order_id
    WHERE e.leg = 'PARENT'
    GROUP BY o.symbol
    HAVING ABS(qty) > 0;
    """
    print("Переопределяем VIEW positions...")
    cur = conn.cursor()
    cur.execute("DROP VIEW IF EXISTS positions;")
    cur.execute(sql)
    cur.close()


def init_pnl_view(conn: sqlite3.Connection) -> None:
    """
    Создаёт VIEW v_order_pnl_r — простая заглушка для риск-модуля.

    Задача:
      - чтобы VIEW существовал;
      - чтобы в нём были как минимум order_id и базовые поля,
        которые может ожидать риск-модуль / отчёты по PnL.

    PnL сейчас везде = 0.0 — позже можно заменить на реальный расчёт.
    """
    print("Переопределяем VIEW v_order_pnl_r (заглушка)...")
    cur = conn.cursor()
    cur.execute("DROP VIEW IF EXISTS v_order_pnl_r;")
    cur.execute("""
        CREATE VIEW v_order_pnl_r AS
        WITH ex AS (
            SELECT
                o.order_id                AS order_id,
                o.symbol                  AS symbol,
                o.side                    AS side,
                o.qty                     AS order_qty,
                COALESCE(SUM(
                    CASE
                        WHEN e.leg = 'PARENT' THEN e.qty
                        ELSE 0
                    END
                ), 0.0)                   AS filled_qty,
                COALESCE(SUM(
                    CASE
                        WHEN e.leg = 'PARENT' THEN e.fee
                        ELSE 0.0
                    END
                ), 0.0)                   AS total_fee
            FROM orders o
            LEFT JOIN executions e
                ON e.order_id = o.order_id
            GROUP BY
                o.order_id, o.symbol, o.side, o.qty
        )
        SELECT
            order_id,
            symbol,
            side,
            order_qty,
            filled_qty,
            total_fee,
            0.0 AS realized_pnl,
            0.0 AS unrealized_pnl,
            0.0 AS total_pnl,
            0.0 AS gross_pnl,
            0.0 AS net_pnl
        FROM ex;
    """)
    cur.close()


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"База не найдена: {DB_PATH}")

    print(f"Используем БД: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    try:
        ensure_orders_last_update_column(conn)
        init_positions_view(conn)
        init_pnl_view(conn)
        conn.commit()
    finally:
        conn.close()

    print("Схема обновлена: orders.last_update_ts_utc + VIEW positions + VIEW v_order_pnl_r.")


if __name__ == "__main__":
    main()
