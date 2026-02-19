"""Authentication service."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User, PasswordReset
from src.auth.schemas import RegisterRequest, RegisterResponse, LoginRequest, LoginResponse, PasswordResetRequest, PasswordResetConfirmRequest, MessageResponse
from src.auth.utils import hash_password, validate_password_strength, verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, generate_reset_token


class AuthService:
    """Authentication service for user operations."""

    def __init__(self, db: AsyncSession):
        """Initialize the auth service with a database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def register(self, request: RegisterRequest) -> RegisterResponse:
        """Register a new user account.

        Args:
            request: Registration request with email and password

        Returns:
            RegisterResponse with user_id, email, and message

        Raises:
            ValueError: If email already exists or password is weak
        """
        # Validate password strength
        is_valid, error_msg = validate_password_strength(request.password)
        if not is_valid:
            raise ValueError(error_msg)

        # Check if email already exists
        stmt = select(User).where(User.email == request.email)
        result = await self.db.execute(stmt)
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise ValueError("Email already registered")

        # Create new user
        user = User(
            email=request.email,
            password_hash=hash_password(request.password),
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return RegisterResponse(
            user_id=user.id,
            email=user.email,
            message="User registered successfully",
        )

    async def login(self, request: LoginRequest) -> LoginResponse:
        """Authenticate a user and return an access token.

        Args:
            request: Login request with email and password

        Returns:
            LoginResponse with access_token, token_type, and expires_in

        Raises:
            ValueError: If credentials are invalid
        """
        # Find user by email
        stmt = select(User).where(User.email == request.email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("Invalid credentials")

        # Verify password
        if not verify_password(request.password, user.password_hash):
            raise ValueError("Invalid credentials")

        # Check if user is active
        if not user.is_active:
            raise ValueError("User account is inactive")

        # Create access token
        token_data = {"sub": str(user.id), "email": user.email}
        access_token = create_access_token(token_data)

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def request_password_reset(self, request: PasswordResetRequest) -> MessageResponse:
        """Request a password reset for a user.

        Args:
            request: Password reset request with user's email

        Returns:
            MessageResponse confirming the reset email was sent

        Note:
            For security, we always return success even if the email doesn't exist
            to prevent email enumeration attacks.
        """
        # Find user by email
        stmt = select(User).where(User.email == request.email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        # Always return success for security (prevents email enumeration)
        if not user:
            return MessageResponse(
                message="If the email exists, a password reset link has been sent"
            )

        # Generate reset token
        reset_token = generate_reset_token()

        # Create password reset record
        password_reset = PasswordReset(
            user_id=user.id,
            token=reset_token,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        self.db.add(password_reset)
        await self.db.commit()

        # In production, send email here
        # For now, we just return success

        return MessageResponse(
            message="If the email exists, a password reset link has been sent"
        )

    async def confirm_password_reset(self, request: PasswordResetConfirmRequest) -> MessageResponse:
        """Confirm a password reset by validating token and updating password.

        Args:
            request: Password reset confirmation with token and new password

        Returns:
            MessageResponse confirming password was reset

        Raises:
            ValueError: If token is invalid, expired, or password is weak
        """
        # Validate password strength
        is_valid, error_msg = validate_password_strength(request.new_password)
        if not is_valid:
            raise ValueError(error_msg)

        # Find password reset token
        stmt = select(PasswordReset).where(PasswordReset.token == request.token)
        result = await self.db.execute(stmt)
        password_reset = result.scalar_one_or_none()

        if not password_reset:
            raise ValueError("Invalid reset token")

        # Check if token is already used
        if password_reset.used_at:
            raise ValueError("Reset token has already been used")

        # Check if token is expired
        if password_reset.expires_at < datetime.utcnow():
            raise ValueError("Reset token has expired")

        # Get the user
        stmt = select(User).where(User.id == password_reset.user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        # Update user's password
        user.password_hash = hash_password(request.new_password)
        await self.db.commit()

        # Mark token as used
        password_reset.used_at = datetime.utcnow()
        await self.db.commit()

        return MessageResponse(message="Password has been reset successfully")
