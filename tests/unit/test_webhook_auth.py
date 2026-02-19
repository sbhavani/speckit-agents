"""Unit tests for webhook authentication."""

import pytest
from src.webhook.auth import WebhookAuth


class TestWebhookAuth:
    """Tests for WebhookAuth HMAC-SHA256 authentication."""

    def setup_method(self):
        """Set up test fixtures."""
        self.secret = "test-secret-key-12345"
        self.auth = WebhookAuth(self.secret)

    def test_verify_signature_valid(self):
        """Test that a valid signature is accepted."""
        payload = b'{"feature": "Add user authentication"}'
        signature = self.auth.sign_payload(payload)

        result = self.auth.verify_signature(payload, signature)

        assert result is True

    def test_verify_signature_invalid(self):
        """Test that an invalid signature is rejected."""
        payload = b'{"feature": "Add user authentication"}'
        invalid_signature = "invalid-signature-hash"

        result = self.auth.verify_signature(payload, invalid_signature)

        assert result is False

    def test_verify_signature_missing(self):
        """Test that missing signature is rejected."""
        payload = b'{"feature": "Add user authentication"}'

        result = self.auth.verify_signature(payload, None)

        assert result is False

    def test_verify_signature_empty_string(self):
        """Test that empty signature string is rejected."""
        payload = b'{"feature": "Add user authentication"}'

        result = self.auth.verify_signature(payload, "")

        assert result is False

    def test_verify_signature_tampered_payload(self):
        """Test that signature fails if payload is modified."""
        original_payload = b'{"feature": "Add user authentication"}'
        signature = self.auth.sign_payload(original_payload)

        tampered_payload = b'{"feature": "Remove user authentication"}'
        result = self.auth.verify_signature(tampered_payload, signature)

        assert result is False

    def test_sign_payload_returns_hex_string(self):
        """Test that sign_payload returns a hex-encoded string."""
        payload = b'{"feature": "Test feature"}'

        signature = self.auth.sign_payload(payload)

        # Should be a 64-character hex string (SHA256 = 32 bytes = 64 hex chars)
        assert isinstance(signature, str)
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_payload_consistent(self):
        """Test that same payload produces same signature."""
        payload = b'{"feature": "Test feature"}'

        sig1 = self.auth.sign_payload(payload)
        sig2 = self.auth.sign_payload(payload)

        assert sig1 == sig2

    def test_sign_payload_different_secrets(self):
        """Test that different secrets produce different signatures."""
        payload = b'{"feature": "Test feature"}'

        auth1 = WebhookAuth("secret1")
        auth2 = WebhookAuth("secret2")

        sig1 = auth1.sign_payload(payload)
        sig2 = auth2.sign_payload(payload)

        assert sig1 != sig2

    def test_sign_payload_different_payloads(self):
        """Test that different payloads produce different signatures."""
        secret = "test-secret"

        auth = WebhookAuth(secret)
        sig1 = auth.sign_payload(b'{"feature": "Feature A"}')
        sig2 = auth.sign_payload(b'{"feature": "Feature B"}')

        assert sig1 != sig2

    def test_verify_signature_with_unicode_secret(self):
        """Test that unicode secrets work correctly."""
        payload = b'{"feature": "Test"}'

        auth = WebhookAuth("unicode-secret-密钥")
        signature = auth.sign_payload(payload)

        result = auth.verify_signature(payload, signature)

        assert result is True

    def test_init_accepts_bytes_secret(self):
        """Test that __init__ accepts bytes secret."""
        auth = WebhookAuth(b"bytes-secret-key")

        payload = b'test'
        signature = auth.sign_payload(payload)
        result = auth.verify_signature(payload, signature)

        assert result is True

    def test_init_accepts_string_secret(self):
        """Test that __init__ accepts string secret."""
        auth = WebhookAuth("string-secret-key")

        payload = b'test'
        signature = auth.sign_payload(payload)
        result = auth.verify_signature(payload, signature)

        assert result is True

    def test_verify_signature_timing_consistent(self):
        """Test that verification timing is consistent (no timing attacks)."""
        payload = b'{"feature": "Test"}'
        signature = self.auth.sign_payload(payload)

        # Run multiple times to ensure consistent timing behavior
        results = [self.auth.verify_signature(payload, signature) for _ in range(10)]

        assert all(results)

    def test_verify_signature_case_sensitive(self):
        """Test that signature verification is case sensitive."""
        payload = b'{"feature": "Test"}'
        signature = self.auth.sign_payload(payload)

        # Modify case of signature
        upper_signature = signature.upper()

        result = self.auth.verify_signature(payload, upper_signature)

        assert result is False
