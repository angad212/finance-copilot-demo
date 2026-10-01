from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agents.query import answer_question
from audit import audit
from db import get_session
from llm import get_llm
from models import User
from ratelimit import rate_limit
from schemas import QueryIn, QueryOut

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryOut)
async def query(
    payload: QueryIn,
    user: User = Depends(rate_limit("query", 20, 60)),
    session: AsyncSession = Depends(get_session),
    llm=Depends(get_llm),
):
    if llm is None:
        raise HTTPException(503, "The assistant is not configured. Set ANTHROPIC_API_KEY on the server.")
    result = await answer_question(llm, user.id, payload.question)
    await audit(session, user.id, "query", f"refused={result['refused']} sql_count={len(result['sql'])}")
    await session.commit()
    return result
