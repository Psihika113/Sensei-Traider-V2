# app/stats.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from app.db import Database


# ==========================
#  Модели статистики
# ==========================


@dataclass
class MonthlyStats:
    """
    Аггрегированная статистика по сделкам за период (обычно за месяц).
    Базируется на pnl_net и rr из таблицы trades.
    """

    period_start: date
    period_end: date  # включительно

    total_trades: int
    closed_trades: int
    win_trades: int
    loss_trades: int
    breakeven_trades: int

    gross_profit: float
    gross_loss: float  # отрицательная сумма по убыточным
    net_pnl: float

    win_rate: float  # доля прибыльных среди закрытых
    avg_rr: float    # среднее RR по закрытым
    avg_pnl_per_trade: float

    max_drawdown: float  # максимальная просадка по equity-curve из pnl_net


# ==========================
#  Вспомогательные функции
# ==========================


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """
    Возвращает (first_day, last_day) месяца.
    """
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return first, last


def _parse_local_date_from_str(s: str) -> Optional[date]:
    """
    Разбор даты из строки формата 'YYYY-MM-DD...' (например '2025-09-23T13:45:00').

    Если строка пустая или формат кривой — возвращаем None (но это не критично
    для расчёта статистики, т.к. используем период по entry_time_local).
    """
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _compute_max_drawdown(pnls: List[float]) -> float:
    """
    Максимальная просадка по equity-curve, построенной по последовательности pnl_net.

    pnls: список pnl_net по сделкам в хронологическом порядке.
    """
    equity = 0.0
    peak = 0.0
    max_dd = 0.0

    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        drawdown = equity - peak
        if drawdown < max_dd:
            max_dd = drawdown

    return max_dd  # отрицательное число (просадка); по желанию можно взять abs()


# ==========================
#  Основные функции
# ==========================


def compute_monthly_stats(db: Database, year: int, month: int) -> MonthlyStats:
    """
    Считает статистику по таблице trades за указанный месяц.

    Ожидается, что в таблице trades есть поля:
        entry_time_local  TEXT
        exit_time_local   TEXT (может быть NULL/пустым для открытых)
        pnl_net           REAL (может быть NULL для открытых)
        rr                REAL (RR сделки на момент входа)
        status            TEXT (например, 'OPEN', 'CLOSED', 'CANCELLED')

    Если какие-то поля отсутствуют — код нужно будет слегка адаптировать под фактическую схему.
    """

    period_start, period_end = _month_bounds(year, month)

    # Берём сделки, у которых дата входа попадает в интервал [first_day, first_day_next_month)
    period_start_str = period_start.isoformat()
    next_month_start = (period_end + timedelta(days=1)).isoformat()

    sql = """
    SELECT
        entry_time_local,
        exit_time_local,
        pnl_net,
        rr,
        status
    FROM trades
    WHERE entry_time_local >= ?
      AND entry_time_local < ?
    ORDER BY entry_time_local ASC
    """
    rows = db.query_all(sql, (period_start_str, next_month_start))

    total_trades = 0
    closed_trades = 0
    win_trades = 0
    loss_trades = 0
    breakeven_trades = 0

    gross_profit = 0.0
    gross_loss = 0.0
    net_pnl = 0.0

    rr_sum = 0.0
    rr_count = 0

    pnl_sequence: List[float] = []

    for row in rows:
        total_trades += 1

        status = (row["status"] or "").upper()
        pnl_net_val = row["pnl_net"]
        rr_val = row["rr"]

        # Закрытые сделки — те, у кого есть exit_time_local и статус не OPEN
        closed = bool(row["exit_time_local"]) and status != "OPEN"
        if closed:
            closed_trades += 1

        # Обрабатываем pnl_net только если он не NULL и числовой
        if pnl_net_val is not None:
            try:
                pnl = float(pnl_net_val)
            except (TypeError, ValueError):
                pnl = 0.0
            net_pnl += pnl
            pnl_sequence.append(pnl)

            if closed:
                if pnl > 0:
                    win_trades += 1
                    gross_profit += pnl
                elif pnl < 0:
                    loss_trades += 1
                    gross_loss += pnl
                else:
                    breakeven_trades += 1

        # RR учитываем только для закрытых сделок с валидным значением
        if closed and rr_val is not None:
            try:
                rr_f = float(rr_val)
            except (TypeError, ValueError):
                rr_f = 0.0
            rr_sum += rr_f
            rr_count += 1

    # win_rate и avg_rr
    win_rate = (win_trades / closed_trades) if closed_trades > 0 else 0.0
    avg_rr = (rr_sum / rr_count) if rr_count > 0 else 0.0
    avg_pnl_per_trade = (net_pnl / total_trades) if total_trades > 0 else 0.0

    max_drawdown = _compute_max_drawdown(pnl_sequence) if pnl_sequence else 0.0

    return MonthlyStats(
        period_start=period_start,
        period_end=period_end,
        total_trades=total_trades,
        closed_trades=closed_trades,
        win_trades=win_trades,
        loss_trades=loss_trades,
        breakeven_trades=breakeven_trades,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        win_rate=win_rate,
        avg_rr=avg_rr,
        avg_pnl_per_trade=avg_pnl_per_trade,
        max_drawdown=max_drawdown,
    )


def format_monthly_report_text(stats: MonthlyStats) -> str:
    """
    Формирует человекочитаемый/Telegram-готовый отчёт за месяц (Markdown).
    Используемся в связке с Notifier.
    """

    s = stats  # короче писать

    period_str = f"{s.period_start:%Y-%m-%d} — {s.period_end:%Y-%m-%d}"

    # Чуть красивых чисел
    def f2(x: float) -> str:
        return f"{x:.2f}"

    win_rate_pct = s.win_rate * 100.0
    max_dd_abs = abs(s.max_drawdown)

    lines: list[str] = []

    lines.append("📅 *Месячный отчёт SenseiTrader*")
    lines.append(f"_Период:_ {period_str}")
    lines.append("")
    lines.append("*Общая статистика*")
    lines.append(f"- Всего сделок: *{s.total_trades}*")
    lines.append(f"- Закрытых: *{s.closed_trades}*")
    lines.append(
        f"- Win/Loss/BE: *{s.win_trades} / {s.loss_trades} / {s.breakeven_trades}* "
        f"(win-rate: *{win_rate_pct:.1f}%*)"
    )
    lines.append("")
    lines.append("*P&L*")
    lines.append(f"- Валовая прибыль: *{f2(s.gross_profit)}*")
    lines.append(f"- Валовый убыток: *{f2(s.gross_loss)}*")
    lines.append(f"- Чистый результат (net PnL): *{f2(s.net_pnl)}*")
    lines.append(f"- Средний PnL на сделку: *{f2(s.avg_pnl_per_trade)}*")
    lines.append("")
    lines.append("*Качество сделок*")
    lines.append(f"- Средний RR по закрытым: *{f2(s.avg_rr)}*")
    lines.append(f"- Макс. просадка по equity (по закрытым): *{f2(max_dd_abs)}*")

    return "\n".join(lines)


# ==========================
#  Хелпер для текущего/прошлого месяца
# ==========================


def compute_last_month_stats(db: Database, today: Optional[date] = None) -> MonthlyStats:
    """
    Удобный хелпер: считает статистику за ПРОШЛЫЙ месяц.
    Полезно вызывать 1-го числа нового месяца для отчёта.
    """
    if today is None:
        today = date.today()

    if today.month == 1:
        year = today.year - 1
        month = 12
    else:
        year = today.year
        month = today.month - 1

    return compute_monthly_stats(db, year, month)
