from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# ==========
#  ENUMS
# ==========


class AssetClass(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    # v2+: futures, options, etc.


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"  # для будущих шортов / деривативов


class EntryType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"   # good-till-cancelled
    IOC = "IOC"   # immediate-or-cancel
    FOK = "FOK"   # fill-or-kill


class OrderType(str, Enum):
    MKT = "MKT"
    LMT = "LMT"
    STP = "STP"
    STP_LMT = "STP_LMT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    PENDING_CANCEL = "PENDING_CANCEL"
    PENDING_MODIFY = "PENDING_MODIFY"
    ERROR = "ERROR"


class ExecutionStatus(str, Enum):
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"  # на будущее


class ApprovalReason(str, Enum):
    OK = "OK"

    LOW_PROBABILITY = "LOW_PROBABILITY"
    NEGATIVE_EV = "NEGATIVE_EV"
    LOW_RR = "LOW_RR"
    OVER_TRADE_RISK_CAP = "OVER_TRADE_RISK_CAP"
    OVER_DAILY_LOSS_LIMIT = "OVER_DAILY_LOSS_LIMIT"
    OVER_EQUITY_UTILIZATION_CAP = "OVER_EQUITY_UTILIZATION_CAP"

    INVALID_SIGNAL = "INVALID_SIGNAL"
    LLM_ERROR = "LLM_ERROR"
    MARKET_CLOSED = "MARKET_CLOSED"
    KILL_SWITCH_ENABLED = "KILL_SWITCH_ENABLED"

    INTERNAL_ERROR = "INTERNAL_ERROR"


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotificationType(str, Enum):
    TRADE_OPENED = "TRADE_OPENED"
    TRADE_CLOSED = "TRADE_CLOSED"
    ORDER_REJECTED = "ORDER_REJECTED"
    DAILY_REPORT = "DAILY_REPORT"
    MONTHLY_REPORT = "MONTHLY_REPORT"
    STATUS = "STATUS"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    RISK_ALERT = "RISK_ALERT"
    SYSTEM_ERROR = "SYSTEM_ERROR"

    # доменные события Risk/Trading
    RISK_REJECT = "RISK_REJECT"       # сигнал отклонён RiskGate
    TRADE_PLACED = "TRADE_PLACED"     # ордер успешно создан/отправлен
    SERVICE_ALERT = "SERVICE_ALERT"   # системные проблемы, алерты сервиса

# ==========
#  BASE MODEL
# ==========


class STBaseModel(BaseModel):
    """Base model for SenseiTrader with strict JSON behaviour."""

    model_config = ConfigDict(
        extra="forbid",          # не позволяем лишние поля
        populate_by_name=True,   # можно использовать alias
        frozen=False,
        str_strip_whitespace=True,
    )


# ==========
#  CORE CONTRACTS
# ==========

class MarketSnapshotV1(STBaseModel):
    bid: float = Field(..., description="Best bid price")
    ask: float = Field(..., description="Best ask price")
    last: Optional[float] = Field(default=None, description="Last trade price (optional)")
    mid: float = Field(..., description="Mid price")
    spread: float = Field(..., ge=0.0, description="ask - bid")
    vol_proxy: Optional[float] = Field(default=None, description="Volatility proxy (optional)")
    liquidity_flags: Optional[list[str]] = Field(default=None, description="Liquidity flags (optional)")

    @field_validator("bid", "ask", "mid")
    @classmethod
    def _prices_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be > 0")
        return v


class EnvelopeV1(STBaseModel):
    """
    Новый входной контракт для контура Envelope+Decision (параллельно legacy Signal).
    На данном этапе используется для ingestion/валидации/архивации файлов.
    """
    schema_version: str = Field(default="sensei.envelope.v1", description="Envelope schema id")

    symbol: str = Field(..., min_length=1, description="Ticker symbol")
    ts_utc: datetime = Field(..., description="Timestamp in UTC")
    session: str = Field(..., min_length=1, description="Market session, e.g. RTH/ETH")

    market_snapshot: MarketSnapshotV1 = Field(..., description="Market snapshot data")

    @field_validator("symbol")
    @classmethod
    def _symbol_upper(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol empty")
        return s
        
class DecisionActionV5(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    WAIT = "WAIT"
    PAUSE = "PAUSE"


class DecisionV5(STBaseModel):
    """
    Decision v5: выход (в SHADOW сначала), без торговых численных параметров.
    """
    schema_version: str = Field(default="sensei.decision.v5", description="Decision schema id")

    action: DecisionActionV5 = Field(..., description="Decision action")
    reason_code: str = Field(..., min_length=1, description="Stable reason code")
    reason_text: str = Field(..., min_length=1, description="Human-readable short reason")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence 0..1")

    guards: list[str] = Field(default_factory=list, description="Guard flags")
    policy_version: str = Field(..., min_length=1, description="Policy version")
    strategy_id: str = Field(..., min_length=1, description="Strategy id")
    ts_utc: datetime = Field(..., description="Decision timestamp UTC")

    @field_validator("reason_code", "policy_version", "strategy_id")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("value empty")
        return s

    @field_validator("guards")
    @classmethod
    def _guards_items(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for it in v:
            s = str(it).strip()
            if s:
                out.append(s)
        return out
        
class OrderPlanV1(STBaseModel):
    """
    Детерминированный план ордера (численные параметры НЕ из LLM).
    """
    schema_version: str = Field(default="sensei.order_plan.v1", description="OrderPlan schema id")

    symbol: str = Field(..., min_length=1, description="Ticker symbol")
    side: Side = Field(..., description="BUY/SELL")
    entry_type: EntryType = Field(..., description="Entry type: MKT/LMT")
    qty: float = Field(..., gt=0.0, description="Quantity")

    entry_price: Optional[float] = Field(default=None, gt=0.0, description="Entry price (if LMT)")
    stop_price: float = Field(..., gt=0.0, description="Stop price")
    take_price: float = Field(..., gt=0.0, description="Take profit price")

    ts_utc: datetime = Field(..., description="Plan timestamp UTC")

    @field_validator("symbol")
    @classmethod
    def _symbol_upper(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol empty")
        return s

    @field_validator("take_price")
    @classmethod
    def _take_gt_stop(cls, v: float, info):
        # Для BUY: take > stop; для SELL (позже) правило будет иным
        return v

class Signal(STBaseModel):
    """
    Торговый сигнал от Sensei к сервису.
    Это тот JSON, который LLM должен выдавать строго по контракту.
    """

    schema_version: str = Field(default="1.0", description="Version of the signal schema")

    signal_id: str = Field(..., description="UUIDv7 or similar unique ID for the signal")
    ts_utc: datetime = Field(..., description="Timestamp in UTC when signal was generated")

    symbol: str = Field(..., min_length=1, description="Ticker symbol, e.g. NVDA")
    asset_class: AssetClass = Field(..., description="Asset class, e.g. stock, etf")

    side: Side = Field(..., description="BUY or SELL")
    entry_type: EntryType = Field(..., description="Entry order type (limit/market/stop/...)")

    entry: float = Field(..., gt=0, description="Entry price")
    stop: float = Field(..., gt=0, description="Stop-loss price")
    take: float = Field(..., gt=0, description="Take-profit price")

    time_in_force: TimeInForce = Field(TimeInForce.DAY, description="Time-in-force for parent order")

    p_win_raw: float = Field(..., ge=0.0, le=1.0, description="Raw (uncalibrated) win probability from LLM/model")
    risk_pct_equity_max: float = Field(
        ..., gt=0.0, description="Max percentage of equity to risk on this trade (e.g. 0.0075 = 0.75%)"
    )

    notes: Optional[str] = Field(default=None, description="Short rationale / explanation")
    snapshot_hash: str = Field(
        ..., min_length=8, description="sha256 or similar hash of input snapshot used to generate this signal"
    )

    # Optional fields for future extension
    exchange: Optional[str] = Field(default=None, description="Primary listing exchange, e.g. NASDAQ")
    tags: Optional[List[str]] = Field(default=None, description="Arbitrary tags for analysis/debug")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("entry", "stop", "take")
    @classmethod
    def positive_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Price fields must be > 0")
        return v

    @field_validator("snapshot_hash")
    @classmethod
    def hash_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("snapshot_hash cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_price_relations(self) -> "Signal":
        """
        Проверка взаимного расположения цен stop/entry/take.
        Для v1 — основная логика под лонг (BUY), но сразу готовим под шорт.
        """
        if self.entry is None or self.stop is None or self.take is None or self.side is None:
            return self

        if self.side == Side.BUY:
            if not (self.stop < self.entry < self.take):
                raise ValueError(
                    "For BUY: expected stop < entry < take "
                    "(stop-loss below entry, take-profit above entry)"
                )
        elif self.side == Side.SELL:
            if not (self.stop > self.entry > self.take):
                raise ValueError(
                    "For SELL: expected stop > entry > take "
                    "(stop-loss above entry, take-profit below entry)"
                )

        return self


class Approval(STBaseModel):
    """
    Решение RiskGate: допустить/отклонить сигнал, и с какими параметрами.
    Важно: для ОТКЛОНЁННЫХ сигналов qty и risk_usd могут быть 0.
    """

    signal_id: str = Field(..., description="ID of the original signal")
    approved: bool = Field(..., description="Whether the trade is allowed")

    reason: ApprovalReason = Field(..., description="Reason code for approval/rejection")
    reason_detail: Optional[str] = Field(
        default=None, description="Free-form explanation for logs/Sheets"
    )

    p_win_calibrated: float = Field(
        ..., ge=0.0, le=1.0, description="Calibrated probability of win after reliability correction"
    )

    ev_after_costs: float = Field(
        ..., description="Expected value of trade after commissions/slippage (fraction of risk or equity)"
    )

    rr: float = Field(..., gt=0.0, description="Reward-to-risk ratio")

    # Для отказов допускаем 0
    qty: int = Field(..., ge=0, description="Number of shares/contracts to trade (0 when rejected)")
    risk_usd: float = Field(..., ge=0.0, description="Dollar risk on the trade (0 when rejected)")


# ==========
#  ORDER MODELS
# ==========


class OrderLeg(STBaseModel):
    """
    Одна "нога" ордера: может быть market/limit/stop/stop-limit.
    Используется и для родителя, и для детей OCO.
    """

    type: OrderType = Field(..., description="Order type for this leg")
    price: Optional[float] = Field(
        default=None,
        description="Limit or stop price depending on type (None for pure MKT)",
    )
    tif: Optional[TimeInForce] = Field(
        default=None,
        description="Optional TIF override for this leg (otherwise use Order.time_in_force)",
    )
    outside_rth: Optional[bool] = Field(
        default=None,
        description="Allow trading outside regular trading hours for this leg",
    )

    @field_validator("price")
    @classmethod
    def price_positive_if_set(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("OrderLeg.price must be > 0 when provided")
        return v


class OCOChildren(STBaseModel):
    """Stop-loss and take-profit legs that form an OCO pair."""

    stop: OrderLeg = Field(..., description="Stop-loss child order")
    take: OrderLeg = Field(..., description="Take-profit child order")


class Order(STBaseModel):
    """
    Готовый ордер для IBKR-адаптера:
    один родительский ордер + OCO-дети.
    """

    order_id: str = Field(..., description="Deterministic order ID (hash of signal_id, symbol, ts_utc, etc.)")

    symbol: str = Field(..., description="Ticker symbol")
    asset_class: AssetClass = Field(..., description="Asset class")

    side: Side = Field(..., description="BUY / SELL")

    # Общее количество для родительского ордера и обоих детей
    qty: int = Field(..., gt=0, description="Total quantity (shares/contracts) for the bracket")

    parent: OrderLeg = Field(..., description="Parent order")
    oco_children: OCOChildren = Field(..., description="OCO children (stop & take)")

    time_in_force: TimeInForce = Field(
        TimeInForce.DAY, description="Default TIF for the order (usually same as Signal)"
    )

    created_ts_utc: datetime = Field(..., description="When order object was created")
    status: OrderStatus = Field(OrderStatus.NEW, description="Internal order status")

    # for idempotency / bookkeeping
    signal_id: str = Field(..., description="ID of the originating signal")
    approval_id: Optional[str] = Field(default=None, description="Optional approval reference ID")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Order.qty must be > 0")
        return v


# ==========
#  EXECUTIONS / POSITIONS
# ==========


class Execution(STBaseModel):
    """
    Факт исполнения (частичный или полный) от брокера.
    """

    exec_id: str = Field(..., description="Broker-native execution ID")
    order_id: str = Field(..., description="Our internal deterministic order_id")

    ts_utc: datetime = Field(..., description="Execution timestamp in UTC")
    price: float = Field(..., gt=0.0, description="Execution price")
    qty: int = Field(..., gt=0, description="Filled quantity for this execution")
    fee: float = Field(..., ge=0.0, description="Commission/fee charged for this execution")

    status: ExecutionStatus = Field(..., description="Execution status (PARTIAL/FILLED/...)")

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Execution quantity must be > 0")
        return v


class Position(STBaseModel):
    """
    Агрегированная позиция по инструменту.
    Источник истины — БД, строится из orders + executions.
    """

    symbol: str = Field(..., description="Ticker symbol")
    asset_class: AssetClass = Field(..., description="Asset class")

    side: PositionSide = Field(..., description="LONG or SHORT")

    qty: int = Field(..., description="Net position size (shares/contracts)")
    avg_price: float = Field(..., gt=0.0, description="Average entry price of the position")

    realized_pnl: float = Field(0.0, description="Realized PnL for closed part of position (in USD)")
    unrealized_pnl: float = Field(0.0, description="Unrealized PnL for open part (in USD)")

    last_update_ts_utc: datetime = Field(..., description="Last time position was updated")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("qty")
    @classmethod
    def qty_nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Position qty should not be zero; closed positions should not be stored here")
        return v


# ==========
#  RISK SNAPSHOT
# ==========


class RiskSnapshot(STBaseModel):
    """
    Снимок риск-состояния за день.
    Используется для дневного лимита и отчётов.
    """

    as_of_date: datetime = Field(..., description="Date (at start of trading day) in UTC")
    equity_start_day: float = Field(..., gt=0.0, description="Equity at start of day (USD)")
    equity_current: float = Field(..., gt=0.0, description="Current equity estimate (USD)")

    realized_pnl_day: float = Field(..., description="Realized PnL for the day")
    unrealized_pnl_day: float = Field(..., description="Unrealized PnL for open positions")

    daily_loss_limit_pct: float = Field(..., gt=0.0, description="Configured daily loss limit, e.g. 0.02 for -2%")
    kill_switch_triggered: bool = Field(
        False, description="If True, new orders must be rejected until reset"
    )

    equity_utilization: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of equity currently at risk / allocated"
    )

    @property
    def daily_drawdown_pct(self) -> float:
        """
        Текущая просадка дня относительно equity_start_day.
        Положительная величина = просадка (0.02 = -2% от equity_start_day).
        """
        dd = (self.equity_start_day - self.equity_current) / self.equity_start_day
        return max(0.0, dd)


# ==========
#  TELEGRAM NOTIFICATIONS
# ==========


class TelegramNotification(STBaseModel):
    """
    Структурированное уведомление в Telegram.
    Сам по себе бот будет собирать текст на основе этой структуры.
    """

    notification_id: str = Field(..., description="Internal ID of the notification for idempotency")
    ts_utc: datetime = Field(..., description="When notification was created")

    type: NotificationType = Field(..., description="Type of notification (trade opened, report, etc.)")
    severity: NotificationSeverity = Field(..., description="Severity level")

    message: str = Field(..., description="Main message text to send to Telegram")

    symbol: Optional[str] = Field(default=None, description="Optional symbol related to this notification")
    signal_id: Optional[str] = Field(default=None, description="Optional signal_id")
    order_id: Optional[str] = Field(default=None, description="Optional order_id")
    trade_id: Optional[str] = Field(default=None, description="Optional trade_id for Sheets/DB")

    extra: Dict[str, Any] = Field(default_factory=dict, description="Additional structured data for logging/debug")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol_opt(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if v is not None else None
