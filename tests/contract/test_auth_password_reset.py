"""Contract tests for password reset endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta

from src.auth.database import Base, get_db
from src.auth.models import User, PasswordReset
from src.auth.routes import router
from fastapi import FastAPI


# Create in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture
async def app():
    """Create FastAPI app for testing."""
    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        async with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield app

    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """Create database session for testing."""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Create a test user with pre-hashed password."""
    # Pre-hashed password for "TestPass123!"
    user = User(
        email="test@example.com",
        password_hash="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4aYJGY7mKRXy3P/2",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def valid_reset_token(db_session: AsyncSession, test_user: User):
    """Create a valid reset token for the test user."""
    token = "valid_reset_token_12345"
    password_reset = PasswordReset(
        user_id=test_user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.add(password_reset)
    await db_session.commit()
    await db_session.refresh(password_reset)
    return token


@pytest_asyncio.fixture
async def expired_reset_token(db_session: AsyncSession, test_user: User):
    """Create an expired reset token for the test user."""
    token = "expired_reset_token_12345"
    password_reset = PasswordReset(
        user_id=test_user.id,
        token=token,
        expires_at=datetime.utcnow() - timedelta(hours=1),  # Already expired
    )
    db_session.add(password_reset)
    await db_session.commit()
    await db_session.refresh(password_reset)
    return token


@pytest_asyncio.fixture
async def used_reset_token(db_session: AsyncSession, test_user: User):
    """Create a used reset token for the test user."""
    token = "used_reset_token_12345"
    password_reset = PasswordReset(
        user_id=test_user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        used_at=datetime.utcnow(),  # Already used
    )
    db_session.add(password_reset)
    await db_session.commit()
    await db_session.refresh(password_reset)
    return token


# ===== POST /auth/password-reset tests =====


@pytest.mark.asyncio
async def test_password_reset_with_valid_email(app: FastAPI, test_user: User):
    """Test requesting password reset with valid email returns 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset",
            json={"email": "test@example.com"}
        )
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    # Security: message doesn't reveal if email exists
    assert "password reset link has been sent" in data["message"].lower()


@pytest.mark.asyncio
async def test_password_reset_with_nonexistent_email(app: FastAPI):
    """Test requesting password reset with non-existent email returns 200 for security."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset",
            json={"email": "nonexistent@example.com"}
        )
    # Security: always return 200 to prevent email enumeration
    assert response.status_code == 200
    data = response.json()
    assert "message" in data


@pytest.mark.asyncio
async def test_password_reset_with_invalid_email_format(app: FastAPI):
    """Test requesting password reset with invalid email format returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset",
            json={"email": "invalid-email"}
        )
    assert response.status_code == 422  # Pydantic validation error


# ===== POST /auth/password-reset/confirm tests =====


@pytest.mark.asyncio
async def test_password_reset_confirm_with_valid_token(app: FastAPI, valid_reset_token: str, test_user: User):
    """Test confirming password reset with valid token returns 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={
                "token": valid_reset_token,
                "new_password": "NewSecurePass123!"
            }
        )
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "successfully" in data["message"].lower()


@pytest.mark.asyncio
async def test_password_reset_confirm_with_invalid_token(app: FastAPI):
    """Test confirming password reset with invalid token returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={
                "token": "nonexistent_token",
                "new_password": "NewSecurePass123!"
            }
        )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_password_reset_confirm_with_expired_token(app: FastAPI, expired_reset_token: str):
    """Test confirming password reset with expired token returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={
                "token": expired_reset_token,
                "new_password": "NewSecurePass123!"
            }
        )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "expired" in data["detail"].lower()


@pytest.mark.asyncio
async def test_password_reset_confirm_with_used_token(app: FastAPI, used_reset_token: str):
    """Test confirming password reset with already used token returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={
                "token": used_reset_token,
                "new_password": "NewSecurePass123!"
            }
        )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "already been used" in data["detail"].lower()


@pytest.mark.asyncio
async def test_password_reset_confirm_with_weak_password(app: FastAPI, valid_reset_token: str):
    """Test confirming password reset with weak password returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={
                "token": valid_reset_token,
                "new_password": "Password1"  # 8+ chars but missing special character
            }
        )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_password_reset_confirm_missing_token(app: FastAPI):
    """Test confirming password reset without token returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={"new_password": "NewSecurePass123!"}
        )
    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_password_reset_confirm_missing_new_password(app: FastAPI, valid_reset_token: str):
    """Test confirming password reset without new password returns 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/password-reset/confirm",
            json={"token": valid_reset_token}
        )
    assert response.status_code == 422  # Pydantic validation error
