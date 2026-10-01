import json
import time

from sqlalchemy import select

from categorizer import categorize
from ledger import category_line, is_uncategorized, txn_amount, upsert_vendor_cache
from models import Account, AgentRun, VendorCategory
from redaction import redact
from vendors import normalize_vendor


async def categorize_transaction(session, llm, user_id: int, txn) -> str:
    """Categorize one transaction. Returns: categorized | cache_hit | needs_review."""
    line = category_line(txn)
    clean_text = redact(txn.description)
    run = AgentRun(
        user_id=user_id, transaction_id=txn.id, agent="categorizer",
        status="ok", input_text=f"{clean_text} | {txn_amount(txn)}",
    )
    session.add(run)

    if line is None:
        txn.status = "needs_review"
        run.status, run.error = "needs_review", "no expense or income line to categorize"
        return "needs_review"

    rows = await session.scalars(
        select(Account).where(Account.user_id == user_id, Account.type == line.account.type)
    )
    candidates = [a for a in rows.all() if not is_uncategorized(a.name)]
    by_name = {a.name: a for a in candidates}
    vendor = normalize_vendor(clean_text)

    cached = await session.scalar(
        select(VendorCategory).where(VendorCategory.user_id == user_id, VendorCategory.vendor_key == vendor)
    )
    cached_account = next((a for a in candidates if cached and a.id == cached.account_id), None)
    if cached_account:
        line.account = cached_account
        txn.status = "categorized"
        run.status, run.output_text = "cache_hit", json.dumps({"category": cached_account.name})
        return "cache_hit"

    if llm is None:
        txn.status = "needs_review"
        run.status, run.error = "skipped", "LLM not configured"
        return "needs_review"

    started = time.perf_counter()
    result = await categorize(llm, clean_text, txn_amount(txn), list(by_name))
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.attempts = result.attempts
    run.input_tokens, run.output_tokens = result.input_tokens, result.output_tokens
    run.output_text = result.raw
    run.error = result.error

    if result.status == "categorized":
        account = by_name[result.category]
        line.account = account
        txn.status = "categorized"
        await upsert_vendor_cache(session, user_id, vendor, account.id, "llm")
        return "categorized"

    txn.status = "needs_review"
    run.status = "failed" if result.error and result.error.startswith("LLM request failed") else "needs_review"
    return "needs_review"
