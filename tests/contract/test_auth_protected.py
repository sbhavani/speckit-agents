"""Contract tests for protected authentication routes."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.auth.database import Base, get_db
from src.auth.models import User
from src.auth.routes import router
from src.auth.utils import hash_password, create_access_token
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
        password_hash="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4aYJGY7mKRXy3P/2",  # "TestPass123!"
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_token(test_user: User):
    """Create a valid auth token for test user."""
    return create_access_token({"sub": str(test_user.id), "email": test_user.email})


@pytest.mark.asyncio
async def test_protected_route_with_valid_token(app: FastAPI, auth_token: str):
    """Test accessing protected route with valid token returns 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_protected_route_without_token(app: FastAPI):
    """Test accessing protected route without token returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/me")
    assert response.status_code == 401  # FastAPI returns 401 for missing credentials


@pytest.mark.asyncio
async def test_protected_route_with_invalid_token(app: FastAPI):
    """Test accessing protected route with invalid token returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid_token"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_requires_auth(app: FastAPI):
    """Test logout endpoint requires authentication."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/logout")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_valid_token(app: FastAPI, auth_token: str):
    """Test logout with valid token returns 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out successfully"
