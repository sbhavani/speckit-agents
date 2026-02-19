"""Webhook server authentication module."""

import hmac
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WebhookAuth:
    """HMAC-SHA256 webhook authentication."""

    def __init__(self, secret: str):
        self.secret = secret.encode() if isinstance(secret, str) else secret

    def verify_signature(self, payload: bytes, signature: Optional[str]) -> bool:
        """Verify the HMAC-SHA256 signature of a request payload.

        Args:
            payload: Raw request body bytes
            signature: Signature from X-Webhook-Signature header

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature:
            logger.warning("No signature provided")
            return False

        expected = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def sign_payload(self, payload: bytes) -> str:
        """Generate HMAC-SHA256 signature for a payload.

        Args:
            payload: Raw request body bytes

        Returns:
            Hex-encoded signature
        """
        return hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
