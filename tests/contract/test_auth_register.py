"""Contract tests for POST /auth/register endpoint.

Tests the user registration endpoint against the OpenAPI contract:
- Valid email + password → 201 Created with user_id
- Duplicate email → 409 Conflict
- Invalid email format → 422 Unprocessable Entity (Pydantic validation)
- Weak password → 400 Bad Request (service-level validation) or 422 (Pydantic validation)
"""

import pytest
import pytest_asyncio
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
async def existing_user(db_session: AsyncSession):
    """Create an existing user for duplicate email testing."""
    # Pre-hashed password for "TestPass123!"
    user = User(
        email="existing@example.com",
        password_hash="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4aYJGY7mKRXy3P/2",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_register_valid_email_and_password(app: FastAPI):
    """Test successful user registration with valid credentials returns 201."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass1!",
            },
        )

    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    data = response.json()
    assert "user_id" in data
    assert data["email"] == "newuser@example.com"
    assert data["message"] == "User registered successfully"


@pytest.mark.asyncio
async def test_register_duplicate_email(app: FastAPI, existing_user: User):
    """Test registration with duplicate email returns 409 Conflict."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "existing@example.com",
                "password": "SecurePass1!",
            },
        )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.text}"
    data = response.json()
    assert "detail" in data
    assert "already registered" in data["detail"].lower()


@pytest.mark.asyncio
async def test_register_invalid_email_format(app: FastAPI):
    """Test registration with invalid email format returns 422 Unprocessable Entity.

    Note: Pydantic's EmailStr validation returns 422, not 400.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "SecurePass1!",
            },
        )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_register_weak_password_too_short(app: FastAPI):
    """Test registration with password too short returns 422 Unprocessable Entity.

    Note: Pydantic's min_length validation returns 422, not 400.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
                "password": "Short1!",
            },
        )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_register_weak_password_no_uppercase(app: FastAPI):
    """Test registration with password missing uppercase returns 400 Bad Request."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
                "password": "nouppercase1!",
            },
        )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    data = response.json()
    assert "detail" in data
    assert "uppercase" in data["detail"].lower()


@pytest.mark.asyncio
async def test_register_weak_password_no_lowercase(app: FastAPI):
    """Test registration with password missing lowercase returns 400 Bad Request."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
                "password": "NOLOWERCASE1!",
            },
        )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    data = response.json()
    assert "detail" in data
    assert "lowercase" in data["detail"].lower()


@pytest.mark.asyncio
async def test_register_weak_password_no_digit(app: FastAPI):
    """Test registration with password missing digit returns 400 Bad Request."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
                "password": "NoDigits!",
            },
        )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    data = response.json()
    assert "detail" in data
    assert "digit" in data["detail"].lower()


@pytest.mark.asyncio
async def test_register_weak_password_no_special(app: FastAPI):
    """Test registration with password missing special character returns 400 Bad Request."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
                "password": "NoSpecial1",
            },
        )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    data = response.json()
    assert "detail" in data
    assert "special" in data["detail"].lower()


@pytest.mark.asyncio
async def test_register_missing_email(app: FastAPI):
    """Test registration with missing email returns 422 Unprocessable Entity."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "password": "SecurePass1!",
            },
        )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_register_missing_password(app: FastAPI):
    """Test registration with missing password returns 422 Unprocessable Entity."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
            },
        )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_register_empty_request(app: FastAPI):
    """Test registration with empty request returns 422 Unprocessable Entity."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={},
        )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
