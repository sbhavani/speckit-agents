"""Pydantic schemas for authentication."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Request schema for user registration."""

    email: EmailStr = Field(..., max_length=254, description="User's email address")
    password: str = Field(..., min_length=8, max_length=128, description="User's password")


class LoginRequest(BaseModel):
    """Request schema for user login."""

    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    """Request schema for requesting password reset."""

    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    """Request schema for confirming password reset."""

    token: str = Field(..., description="Password reset token from email")
    new_password: str = Field(..., min_length=8, max_length=128, description="New password")


class RegisterResponse(BaseModel):
    """Response schema for successful registration."""

    user_id: uuid.UUID
    email: EmailStr
    message: str


class LoginResponse(BaseModel):
    """Response schema for successful login."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token expiration in seconds")


class UserResponse(BaseModel):
    """Response schema for user data."""

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class ErrorResponse(BaseModel):
    """Error response schema."""

    detail: str
