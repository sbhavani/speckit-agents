"""Authentication configuration schema."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PasswordRequirements(BaseSettings):
    """Password strength requirements configuration."""

    min_length: int = Field(default=8, ge=8, le=128, description="Minimum password length")
    require_uppercase: bool = Field(default=True, description="Require at least one uppercase letter")
    require_lowercase: bool = Field(default=True, description="Require at least one lowercase letter")
    require_digit: bool = Field(default=True, description="Require at least one digit")
    require_special: bool = Field(default=True, description="Require at least one special character")
    special_chars: str = Field(default="!@#$%^&*()_+-=[]{}|;:,.<>?", description="Allowed special characters")


class AuthSettings(BaseSettings):
    """Main authentication settings."""

    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # JWT Configuration
    jwt_secret: str = Field(default="changeme-insecure-dev-secret", description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm (HS256, HS384, HS512)")
    jwt_expiry_minutes: int = Field(default=30, ge=1, le=1440, description="JWT token expiry in minutes")

    # Session Configuration
    session_timeout_minutes: int = Field(
        default=30, ge=1, le=1440, description="Session timeout in minutes"
    )

    # Password Reset Configuration
    password_reset_token_expiry_hours: int = Field(
        default=24, ge=1, le=72, description="Password reset token expiry in hours"
    )

    # Password Requirements (nested)
    password: PasswordRequirements = Field(default_factory=PasswordRequirements)


# Global settings instance
auth_settings = AuthSettings()
