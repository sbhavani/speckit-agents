"""Unit tests for authentication utilities."""

import pytest
from datetime import datetime, timedelta, timezone

from src.auth.utils import (
    create_access_token,
    decode_access_token,
    validate_password_strength,
    SECRET_KEY,
    ALGORITHM,
)
from jose import jwt


class TestPasswordStrengthValidation:
    """Tests for validate_password_strength function."""

    def test_valid_password(self):
        """Test that a valid password passes all requirements."""
        password = "SecurePass1!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
        assert error == ""

    def test_password_too_short(self):
        """Test that passwords shorter than 8 characters fail."""
        password = "Abc1!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "at least 8 characters" in error

    def test_password_exactly_8_chars(self):
        """Test that a password with exactly 8 characters passes."""
        password = "Abcdef1!"  # 8 chars: uppercase, lowercase, digit, special
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
        assert error == ""

    def test_no_uppercase_letter(self):
        """Test that passwords without uppercase letters fail."""
        password = "securepass1!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "uppercase" in error

    def test_no_lowercase_letter(self):
        """Test that passwords without lowercase letters fail."""
        password = "SECUREPASS1!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "lowercase" in error

    def test_no_digit(self):
        """Test that passwords without digits fail."""
        password = "SecurePass!"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "digit" in error

    def test_no_special_character(self):
        """Test that passwords without special characters fail."""
        password = "SecurePass1"
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "special character" in error

    def test_special_characters_accepted(self):
        """Test that various special characters are accepted."""
        special_chars = ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")", "?", ".", ":", "<", ">"]
        for char in special_chars:
            password = f"Pass1234{char}"
            is_valid, error = validate_password_strength(password)
            assert is_valid is True, f"Password with {char} should be valid"

    def test_only_minimum_length(self):
        """Test password with just minimum length and all requirements."""
        password = "Aa1!aaaa"  # 8 chars: uppercase, lowercase, digit, special
        is_valid, error = validate_password_strength(password)
        assert is_valid is True

    def test_very_long_password(self):
        """Test that very long passwords pass if they meet requirements."""
        password = "MyV3ry$tr0ngP@ssw0rd!" * 3
        is_valid, error = validate_password_strength(password)
        assert is_valid is True
        assert error == ""

    def test_whitespace_in_password(self):
        """Test that passwords with spaces fail (no special char)."""
        password = "Password1 "  # space is not in the special char list
        is_valid, error = validate_password_strength(password)
        assert is_valid is False
        assert "special character" in error


class TestCreateAccessToken:
    """Tests for create_access_token function."""

    def test_create_token_with_default_expiration(self):
        """Test creating a token with default expiration."""
        data = {"sub": "testuser@example.com"}

        token = create_access_token(data)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_with_custom_expiration(self):
        """Test creating a token with custom expiration."""
        data = {"sub": "testuser@example.com"}
        expires_delta = timedelta(minutes=60)

        token = create_access_token(data, expires_delta=expires_delta)

        assert token is not None
        assert isinstance(token, str)

    def test_create_token_with_additional_data(self):
        """Test that additional data is encoded in the token."""
        data = {
            "sub": "testuser@example.com",
            "user_id": 123,
            "role": "admin"
        }

        token = create_access_token(data)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert decoded["sub"] == "testuser@example.com"
        assert decoded["user_id"] == 123
        assert decoded["role"] == "admin"

    def test_create_token_contains_expiration(self):
        """Test that token contains expiration claim."""
        data = {"sub": "testuser@example.com"}

        token = create_access_token(data)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert "exp" in decoded


class TestDecodeAccessToken:
    """Tests for decode_access_token function."""

    def test_decode_valid_token(self):
        """Test decoding a valid token."""
        data = {"sub": "testuser@example.com"}

        token = create_access_token(data)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert decoded["sub"] == "testuser@example.com"

    def test_decode_invalid_token(self):
        """Test decoding an invalid token."""
        invalid_token = "this.is.not.a.valid.token"

        decoded = decode_access_token(invalid_token)

        assert decoded is None

    def test_decode_tampered_token(self):
        """Test decoding a tampered token."""
        data = {"sub": "testuser@example.com"}

        token = create_access_token(data)
        # Tamper with the token by changing a character
        tampered_token = token[:-1] + ("X" if token[-1] != "X" else "Y")

        decoded = decode_access_token(tampered_token)

        assert decoded is None


class TestJWTIntegration:
    """Integration tests for JWT token creation and decoding."""

    def test_roundtrip_token(self):
        """Test that token can be created and decoded back."""
        data = {"sub": "user@example.com", "user_id": 42}

        token = create_access_token(data)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert decoded["sub"] == "user@example.com"
        assert decoded["user_id"] == 42

    def test_token_with_special_characters_in_email(self):
        """Test token creation with special characters in email."""
        data = {"sub": "user+tag@example-domain.co.uk"}

        token = create_access_token(data)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert decoded["sub"] == "user+tag@example-domain.co.uk"


class TestTokenExpiration:
    """Tests for JWT token expiration handling."""

    def test_expired_token_returns_none(self):
        """Test that decoding an expired token returns None."""
        # Create a token that expired 1 hour ago
        data = {"sub": "test@example.com"}
        expired_payload = data.copy()
        expired_payload["exp"] = datetime.utcnow() - timedelta(hours=1)

        # Manually create an expired token
        expired_token = jwt.encode(
            expired_payload, SECRET_KEY, algorithm=ALGORITHM
        )

        # Decode should return None for expired token
        result = decode_access_token(expired_token)

        assert result is None

    def test_token_expired_one_day_ago(self):
        """Test that a token expired one day ago returns None."""
        data = {"sub": "test@example.com"}
        expired_payload = data.copy()
        expired_payload["exp"] = datetime.utcnow() - timedelta(days=1)

        expired_token = jwt.encode(
            expired_payload, SECRET_KEY, algorithm=ALGORITHM
        )

        result = decode_access_token(expired_token)

        assert result is None

    def test_token_with_future_expiration_is_valid(self):
        """Test that a token with future expiration is valid."""
        data = {"sub": "test@example.com"}
        # Token that expires in 1 hour (still valid)
        future_payload = data.copy()
        future_payload["exp"] = datetime.utcnow() + timedelta(hours=1)

        valid_token = jwt.encode(
            future_payload, SECRET_KEY, algorithm=ALGORITHM
        )

        result = decode_access_token(valid_token)

        assert result is not None
        assert result["sub"] == "test@example.com"

    def test_default_expiration_is_30_minutes(self):
        """Test that default token expiration is approximately 30 minutes."""
        data = {"sub": "test@example.com"}
        token = create_access_token(data)

        # Decode the token to check the exp claim
        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        exp_time = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        diff_minutes = (exp_time - now).total_seconds() / 60

        # Should be approximately 30 minutes (between 29 and 31)
        assert 29 <= diff_minutes <= 31

    def test_custom_expiration_is_respected(self):
        """Test that custom expiration delta is used."""
        data = {"sub": "test@example.com"}
        custom_delta = timedelta(hours=2)
        token = create_access_token(data, expires_delta=custom_delta)

        decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        exp_time = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        diff_minutes = (exp_time - now).total_seconds() / 60

        # Should be approximately 120 minutes (between 119 and 121)
        assert 119 <= diff_minutes <= 121


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
