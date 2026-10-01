from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from audit import audit
from db import get_session
from ledger import LOAD_LINES, category_line, load_transaction, upsert_vendor_cache
from models import Account, Transaction, TransactionLine, User
from redaction import redact
from schemas import AccountOut, CategoryOverride, TransactionIn, TransactionOut
from security import get_current_user
from vendors import normalize_vendor

router = APIRouter(tags=["ledger"])


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Account).where(Account.user_id == user.id).order_by(Account.type, Account.name))
    return rows.all()


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    status: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Transaction).where(Transaction.user_id == user.id).options(LOAD_LINES)
    if status:
        stmt = stmt.where(Transaction.status == status)
    stmt = stmt.order_by(Transaction.txn_date.desc(), Transaction.id.desc()).limit(limit)
    return (await session.scalars(stmt)).all()


@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: int, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    txn = await load_transaction(session, user.id, transaction_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    return txn


@router.post("/transactions", response_model=TransactionOut, status_code=201)
async def create_transaction(
    payload: TransactionIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    ids = {line.account_id for line in payload.lines}
    found = set((await session.scalars(
        select(Account.id).where(Account.user_id == user.id, Account.id.in_(ids))
    )).all())
    if ids - found:
        raise HTTPException(400, f"Unknown account ids: {sorted(ids - found)}")

    txn = Transaction(
        user_id=user.id,
        txn_date=payload.txn_date,
        description=redact(payload.description),
        status="pending",
        lines=[TransactionLine(account_id=l.account_id, debit=l.debit, credit=l.credit) for l in payload.lines],
    )
    session.add(txn)
    await audit(session, user.id, "create_transaction")
    await session.commit()
    return await load_transaction(session, user.id, txn.id)


@router.patch("/transactions/{transaction_id}/category", response_model=TransactionOut)
async def override_category(
    transaction_id: int,
    payload: CategoryOverride,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Human review: set the category and teach the vendor cache."""
    txn = await load_transaction(session, user.id, transaction_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    line = category_line(txn)
    if line is None:
        raise HTTPException(400, "This transaction has no category line")
    account = await session.scalar(
        select(Account).where(Account.id == payload.account_id, Account.user_id == user.id)
    )
    if account is None:
        raise HTTPException(400, "Unknown account")
    if account.type != line.account.type:
        raise HTTPException(400, f"Pick an {line.account.type} account for this transaction")

    line.account = account
    txn.status = "categorized"
    await upsert_vendor_cache(session, user.id, normalize_vendor(txn.description), account.id, "manual")
    await audit(session, user.id, "override_category", f"txn {txn.id} -> {account.name}")
    await session.commit()
    return txn
