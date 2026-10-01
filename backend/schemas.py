from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegisterIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    password: str = Field(min_length=8, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    debit: Decimal
    credit: Decimal
    account: AccountOut


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    txn_date: date
    description: str
    status: str
    lines: list[LineOut]


class LineIn(BaseModel):
    account_id: int
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def one_side_only(self):
        if (self.debit == 0) == (self.credit == 0):
            raise ValueError("a line needs either a debit or a credit, not both and not neither")
        return self


class TransactionIn(BaseModel):
    txn_date: date
    description: str = Field(min_length=1, max_length=300)
    lines: list[LineIn] = Field(min_length=2)

    @model_validator(mode="after")
    def must_balance(self):
        total_debit = sum(line.debit for line in self.lines)
        total_credit = sum(line.credit for line in self.lines)
        if total_debit != total_credit:
            raise ValueError(f"debits ({total_debit}) must equal credits ({total_credit})")
        return self


class CategoryOverride(BaseModel):
    account_id: int


class FlagOut(BaseModel):
    id: int
    transaction_id: int
    description: str
    rule: str
    reason: str
    status: str
    llm_verdict: str | None = None
    llm_reasoning: str | None = None


class FlagUpdate(BaseModel):
    status: Literal["open", "confirmed", "dismissed"]


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int | None
    agent: str
    status: str
    attempts: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    input_text: str
    output_text: str | None
    error: str | None
    created_at: datetime


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class QueryOut(BaseModel):
    answer: str
    sql: list[str]
    refused: bool
