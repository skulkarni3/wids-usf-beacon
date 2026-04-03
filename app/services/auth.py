import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import bcrypt

from app.services.pg_pool import get_pool


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


async def create_user(
    name: str,
    email: str,
    password: str,
    address: Optional[str] = None,
) -> str:
    """
    Create a new user in Postgres. Returns the new user_id (UUID string).
    Columns: user_id, name, email, password_hash, address (optional).
    """
    pool = await get_pool()
    email_norm = _normalize_email(email)
    existing = await pool.fetchrow(
        "SELECT user_id FROM users WHERE lower(trim(email)) = $1",
        email_norm,
    )
    if existing:
        raise ValueError("Email already registered")

    password_hash = hash_password(password)
    row = await pool.fetchrow(
        """
        INSERT INTO users (name, email, password_hash, address)
        VALUES ($1, $2, $3, $4)
        RETURNING user_id
        """,
        name.strip(),
        email_norm,
        password_hash,
        address,
    )
    return str(row["user_id"])


async def authenticate_user(email: str, password: str) -> str | None:
    """Verify credentials by email. Returns user_id on success, None on failure."""
    pool = await get_pool()
    email_norm = _normalize_email(email)
    row = await pool.fetchrow(
        "SELECT user_id, password_hash FROM users WHERE lower(trim(email)) = $1",
        email_norm,
    )
    if not row:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return str(row["user_id"])
