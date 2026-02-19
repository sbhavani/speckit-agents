"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.database import get_db
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.auth.schemas import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    UserResponse,
    MessageResponse,
    ErrorResponse,
    PasswordResetRequest,
    PasswordResetConfirmRequest,
)
from src.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request data"},
        409: {"model": ErrorResponse, "description": "Email already registered"},
    },
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new user account.

    Args:
        request: Registration request with email and password
        db: Database session dependency

    Returns:
        RegisterResponse with user_id, email, and message

    Raises:
        HTTPException: 400 for weak password, 409 for duplicate email
    """
    service = AuthService(db)
    try:
        return await service.register(request)
    except ValueError as e:
        error_msg = str(e)
        if "Email already registered" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
    },
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate user and obtain access token.

    Args:
        request: Login request with email and password
        db: Database session dependency

    Returns:
        LoginResponse with access_token, token_type, and expires_in

    Raises:
        HTTPException: 401 for invalid credentials
    """
    service = AuthService(db)
    try:
        return await service.login(request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Get current authenticated user.

    Args:
        current_user: Current authenticated user from dependency

    Returns:
        UserResponse with user data
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def logout(
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """Log out current user.

    Note: Since JWT tokens are stateless, the client should discard the token.
    This endpoint confirms the logout was successful.

    Args:
        current_user: Current authenticated user from dependency

    Returns:
        MessageResponse confirming logout
    """
    return MessageResponse(message="Logged out successfully")


@router.post(
    "/password-reset",
    response_model=MessageResponse,
    responses={
        200: {"description": "Password reset email sent"},
    },
)
async def request_password_reset(
    request: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Request a password reset for a user account.

    Sends a password reset email to the user if the email exists.
    For security, always returns success to prevent email enumeration.

    Args:
        request: Password reset request with user's email
        db: Database session dependency

    Returns:
        MessageResponse confirming the reset email was sent
    """
    service = AuthService(db)
    return await service.request_password_reset(request)


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid token or weak password"},
    },
)
async def confirm_password_reset(
    request: PasswordResetConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Confirm a password reset with the token and new password.

    Args:
        request: Password reset confirmation with token and new password
        db: Database session dependency

    Returns:
        MessageResponse confirming password was reset

    Raises:
        HTTPException: 400 for invalid/expired token or weak password
    """
    service = AuthService(db)
    try:
        return await service.confirm_password_reset(request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
