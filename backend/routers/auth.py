from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from audit import audit
from db import get_session
from ledger import ensure_default_accounts
from models import User
from schemas import RegisterIn, TokenOut
from security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(payload: RegisterIn, session: AsyncSession = Depends(get_session)):
    email = payload.email.lower()
    if await session.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "That email is already registered")
    user = User(email=email, password_hash=hash_password(payload.password))
    session.add(user)
    await session.flush()
    await ensure_default_accounts(session, user.id)
    await audit(session, user.id, "register")
    await session.commit()
    return TokenOut(access_token=create_token(user.id))


@router.post("/login", response_model=TokenOut)
async def login(form: OAuth2PasswordRequestForm = Depends(), session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not verify_password(form.password, user.password_hash):
        await audit(session, None, "login_failed", form.username[:80])
        await session.commit()
        raise HTTPException(401, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    await audit(session, user.id, "login")
    await session.commit()
    return TokenOut(access_token=create_token(user.id))
