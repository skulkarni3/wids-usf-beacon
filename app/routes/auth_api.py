from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from ..services import auth

router = APIRouter()


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    password: str = Field(..., min_length=1)
    address: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


@router.post("/auth/register")
async def register(body: RegisterRequest):
    try:
        user_id = await auth.create_user(
            name=body.name.strip(),
            email=body.email,
            password=body.password,
            address=body.address.strip() if body.address else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"user_id": user_id}


@router.post("/auth/login")
async def login(body: LoginRequest):
    user_id = await auth.authenticate_user(
        email=body.email,
        password=body.password,
    )
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"user_id": user_id}
