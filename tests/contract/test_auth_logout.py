"""Contract tests for POST /auth/logout endpoint.

OpenAPI Specification:
- POST /auth/logout
- Security: BearerAuth required
- 200: Logout successful with MessageResponse
- 401: Not authenticated

Acceptance Criteria:
- Authenticated request -> 200 OK
- Unauthenticated request -> 401 Unauthorized
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.auth.database import Base, get_db
from src.auth.models import User
from src.auth.routes import router
from src.auth.utils import create_access_token
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
    """Create a test user."""
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
async def test_logout_authenticated_returns_200(app: FastAPI, auth_token: str):
    """Test that authenticated logout request returns 200 OK.

    Per acceptance criteria: Authenticated request -> 200 OK
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"] == "Logged out successfully"


@pytest.mark.asyncio
async def test_logout_unauthenticated_returns_401(app: FastAPI):
    """Test that unauthenticated logout request returns 401 Unauthorized.

    Per acceptance criteria: Unauthenticated request -> 401 Unauthorized
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/logout")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_invalid_token_returns_401(app: FastAPI):
    """Test that logout with invalid token returns 401 Unauthorized.

    Invalid/malformed tokens should be rejected with 401.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer invalid_token_12345"}
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_missing_bearer_prefix_returns_401(app: FastAPI):
    """Test that logout without Bearer prefix returns 401 Unauthorized.

    Tokens must include the 'Bearer ' prefix.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": "some_token_without_bearer"}
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_response_schema(app: FastAPI, auth_token: str):
    """Test that logout response matches MessageResponse schema.

    Per OpenAPI spec, response should contain 'message' field.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    assert response.status_code == 200
    data = response.json()
    # Verify response schema matches MessageResponse
    assert "message" in data
    assert isinstance(data["message"], str)
