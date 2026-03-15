"""
Authentication routes for the Health Service.

POST /api/auth/login     — returns a JWT
POST /api/auth/register  — creates a new user account

The get_current_user dependency is used by all protected routes in this service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from health_service.db.models import User
from health_service.db.session import get_db
from shared.jwt_utils import create_access_token, verify_token
from shared.schemas import TokenPayload

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


# ─── Request / Response Schemas ───────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── Dependency ───────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token_payload = verify_token(credentials.credentials)
    if token_payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    user = await db.get(User, token_payload.user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account deleted.",
        )
    return user


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check for existing email (stored encrypted — simplified here)
    stmt = select(User).where(User.email_encrypted == body.email.lower())
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user = User(
        email_encrypted=body.email.lower(),  # TODO: encrypt with ENCRYPTION_KEY
        hashed_password=pwd_context.hash(body.password),
        role="free",
    )
    db.add(user)
    await db.flush()

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(
        User.email_encrypted == body.email.lower(),
        User.deleted_at.is_(None),
    )
    user: User | None = (await db.execute(stmt)).scalar_one_or_none()

    if user is None or not pwd_context.verify(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token)
