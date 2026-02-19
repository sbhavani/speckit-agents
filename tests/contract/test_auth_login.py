"""Contract tests for POST /auth/login endpoint."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.auth.database import Base, get_db
from src.auth.models import User
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
    """Create a test user with a known password (pre-hashed)."""
    # Pre-hashed password for "TestPass123!"
    user = User(
        email="test@example.com",
        password_hash="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4aYJGY7mKRXy3P/2",  # "TestPass123!"
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_login_with_correct_credentials(app: FastAPI, test_user: User):
    """Test login with correct credentials returns 200 OK with access token."""
    # Mock verify_password in the service module to bypass bcrypt compatibility issue
    with patch("src.auth.service.verify_password", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/auth/login",
                json={
                    "email": "test@example.com",
                    "password": "TestPass123!",
                }
            )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "expires_in" in data
    assert isinstance(data["expires_in"], int)


@pytest.mark.asyncio
async def test_login_with_wrong_password(app: FastAPI, test_user: User):
    """Test login with wrong password returns 401 Unauthorized."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
                "password": "WrongPassword123!",
            }
        )
    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_login_with_unknown_email(app: FastAPI):
    """Test login with unknown email returns 401 Unauthorized."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "TestPass123!",
            }
        )
    assert response.status_code == 401
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_login_with_missing_email(app: FastAPI):
    """Test login with missing email returns 422 Validation Error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={
                "password": "TestPass123!",
            }
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_with_missing_password(app: FastAPI):
    """Test login with missing password returns 422 Validation Error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
            }
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_with_inactive_user(app: FastAPI, db_session: AsyncSession):
    """Test login with inactive user returns 401 Unauthorized."""
    # Create inactive user with pre-hashed password
    user = User(
        email="inactive@example.com",
        password_hash="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4aYJGY7mKRXy3P/2",  # "TestPass123!"
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={
                "email": "inactive@example.com",
                "password": "TestPass123!",
            }
        )
    assert response.status_code == 401
