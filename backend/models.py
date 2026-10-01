from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        CheckConstraint("type IN ('asset','liability','equity','income','expense')", name="ck_account_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str]
    type: Mapped[str]


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("status IN ('pending','categorized','needs_review')", name="ck_txn_status"),
        Index("idx_transactions_user_date", "user_id", "txn_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    txn_date: Mapped[date]
    description: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["TransactionLine"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class TransactionLine(Base):
    __tablename__ = "transaction_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_line_nonneg"),
        CheckConstraint("(debit = 0) <> (credit = 0)", name="ck_line_one_side"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")

    transaction: Mapped["Transaction"] = relationship(back_populates="lines")
    account: Mapped["Account"] = relationship()


class AgentRun(Base):
    """One row per agent call: what went in, what came out, how long, what it cost."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    agent: Mapped[str]
    status: Mapped[str]  # ok | cache_hit | needs_review | failed | skipped
    attempts: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Flag(Base):
    __tablename__ = "flags"
    __table_args__ = (UniqueConstraint("transaction_id", "rule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    rule: Mapped[str]
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="open")  # open | confirmed | dismissed | escalated
    llm_verdict: Mapped[str | None]
    llm_reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorCategory(Base):
    """Cache: normalized vendor name -> account, so repeat vendors skip the LLM."""

    __tablename__ = "vendor_categories"
    __table_args__ = (UniqueConstraint("user_id", "vendor_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    vendor_key: Mapped[str]
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    source: Mapped[str]  # llm | manual


class StatementUpload(Base):
    __tablename__ = "statement_uploads"
    __table_args__ = (UniqueConstraint("user_id", "checksum"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str]
    checksum: Mapped[str]
    rows_ok: Mapped[int]
    rows_failed: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None]
    action: Mapped[str]
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
