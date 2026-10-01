import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import run_pipeline
from audit import audit
from db import get_session
from ingest import CSVFormatError, parse_csv
from ledger import build_transaction, ensure_default_accounts
from llm import get_llm
from models import AgentRun, Flag, StatementUpload, Transaction, User
from ratelimit import rate_limit
from redaction import redact
from schemas import AgentRunOut, FlagOut, FlagUpdate
from security import get_current_user

router = APIRouter(tags=["pipeline"])
MAX_UPLOAD_BYTES = 2_000_000


@router.post("/ingest/csv", status_code=201)
async def ingest_csv(
    file: UploadFile = File(...),
    user: User = Depends(rate_limit("ingest", 10, 60)),
    session: AsyncSession = Depends(get_session),
):
    """Columns: date, description, amount (negative = money out). Bad rows are reported, not fatal."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 2 MB")
    checksum = hashlib.sha256(content).hexdigest()
    if await session.scalar(
        select(StatementUpload).where(StatementUpload.user_id == user.id, StatementUpload.checksum == checksum)
    ):
        raise HTTPException(409, "This file was already uploaded")
    try:
        rows, errors = parse_csv(content)
    except CSVFormatError as e:
        raise HTTPException(400, str(e))

    accounts = await ensure_default_accounts(session, user.id)
    for row in rows:  # redact before storage; the raw file is never kept
        session.add(build_transaction(user.id, row.txn_date, redact(row.description), row.amount, accounts))

    upload_id = None
    if rows:
        upload = StatementUpload(
            user_id=user.id, filename=(file.filename or "upload.csv")[:200],
            checksum=checksum, rows_ok=len(rows), rows_failed=len(errors),
        )
        session.add(upload)
        await session.flush()
        upload_id = upload.id
    await audit(session, user.id, "ingest_csv", f"{len(rows)} ok, {len(errors)} failed")
    await session.commit()
    return {"upload_id": upload_id, "inserted": len(rows), "failed": [e.__dict__ for e in errors]}


@router.post("/pipeline/run")
async def pipeline_run(
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(rate_limit("pipeline", 5, 60)),
    session: AsyncSession = Depends(get_session),
    llm=Depends(get_llm),
):
    await audit(session, user.id, "pipeline_run")
    return await run_pipeline(session, llm, user.id, limit)


@router.get("/pipeline/status")
async def pipeline_status(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Transaction.status, func.count()).where(Transaction.user_id == user.id).group_by(Transaction.status)
    )
    counts = {"pending": 0, "categorized": 0, "needs_review": 0, **dict(rows.all())}
    open_flags = await session.scalar(
        select(func.count()).select_from(Flag).where(Flag.user_id == user.id, Flag.status.in_(["open", "escalated"]))
    )
    return {"transactions": counts, "open_flags": open_flags}


@router.get("/flags", response_model=list[FlagOut])
async def list_flags(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Flag, Transaction.description)
        .join(Transaction, Transaction.id == Flag.transaction_id)
        .where(Flag.user_id == user.id)
        .order_by(Flag.id.desc())
    )
    return [
        FlagOut(
            id=f.id, transaction_id=f.transaction_id, description=desc, rule=f.rule, reason=f.reason,
            status=f.status, llm_verdict=f.llm_verdict, llm_reasoning=f.llm_reasoning,
        )
        for f, desc in rows.all()
    ]


@router.patch("/flags/{flag_id}")
async def update_flag(
    flag_id: int, payload: FlagUpdate,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    flag = await session.scalar(select(Flag).where(Flag.id == flag_id, Flag.user_id == user.id))
    if flag is None:
        raise HTTPException(404, "Flag not found")
    flag.status = payload.status
    await audit(session, user.id, "update_flag", f"flag {flag.id} -> {payload.status}")
    await session.commit()
    return {"id": flag.id, "status": flag.status}


@router.get("/agent-runs", response_model=list[AgentRunOut])
async def agent_runs(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(AgentRun).where(AgentRun.user_id == user.id).order_by(AgentRun.id.desc()).limit(limit)
    )
    return rows.all()
