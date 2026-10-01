from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Account, Transaction, TransactionLine, VendorCategory

DEFAULT_ACCOUNTS = [
    ("Bank", "asset"),
    ("Uncategorized Expense", "expense"),
    ("Uncategorized Income", "income"),
    ("Software", "expense"),
    ("Travel", "expense"),
    ("Meals", "expense"),
    ("Rent", "expense"),
    ("Utilities", "expense"),
    ("Marketing", "expense"),
    ("Office Supplies", "expense"),
    ("Sales", "income"),
]

LOAD_LINES = selectinload(Transaction.lines).selectinload(TransactionLine.account)


async def ensure_default_accounts(session: AsyncSession, user_id: int) -> dict[str, Account]:
    rows = await session.scalars(select(Account).where(Account.user_id == user_id))
    accounts = {a.name: a for a in rows.all()}
    for name, type_ in DEFAULT_ACCOUNTS:
        if name not in accounts:
            account = Account(user_id=user_id, name=name, type=type_)
            session.add(account)
            accounts[name] = account
    await session.flush()
    return accounts


def build_transaction(user_id, txn_date, description, signed_amount: Decimal, accounts) -> Transaction:
    """Negative amount = money out (expense), positive = money in (income)."""
    amount = abs(signed_amount)
    zero = Decimal("0")
    if signed_amount < 0:
        lines = [
            TransactionLine(account_id=accounts["Uncategorized Expense"].id, debit=amount, credit=zero),
            TransactionLine(account_id=accounts["Bank"].id, debit=zero, credit=amount),
        ]
    else:
        lines = [
            TransactionLine(account_id=accounts["Bank"].id, debit=amount, credit=zero),
            TransactionLine(account_id=accounts["Uncategorized Income"].id, debit=zero, credit=amount),
        ]
    return Transaction(
        user_id=user_id, txn_date=txn_date, description=description, status="pending", lines=lines
    )


def txn_amount(txn: Transaction) -> Decimal:
    return sum((line.debit for line in txn.lines), Decimal("0"))


def category_line(txn: Transaction) -> TransactionLine | None:
    """The line that carries the category: the expense or income side."""
    return next((line for line in txn.lines if line.account.type in ("expense", "income")), None)


def is_uncategorized(name: str) -> bool:
    return name.lower().startswith("uncategorized")


async def load_transaction(session: AsyncSession, user_id: int, transaction_id: int) -> Transaction | None:
    return await session.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id, Transaction.user_id == user_id)
        .options(LOAD_LINES)
    )


async def upsert_vendor_cache(session, user_id: int, vendor_key: str, account_id: int, source: str) -> None:
    row = await session.scalar(
        select(VendorCategory).where(
            VendorCategory.user_id == user_id, VendorCategory.vendor_key == vendor_key
        )
    )
    if row:
        row.account_id = account_id
        row.source = source
    else:
        session.add(
            VendorCategory(user_id=user_id, vendor_key=vendor_key, account_id=account_id, source=source)
        )
