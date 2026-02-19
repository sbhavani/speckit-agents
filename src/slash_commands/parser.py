"""Slash command parser."""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedCommand:
    """Parsed slash command."""

    command: str
    subcommand: Optional[str]
    args: str
    raw: str


class CommandParser:
    """Parser for Mattermost slash commands."""

    # Default command prefix
    DEFAULT_PREFIX = "/agent-team"

    # Valid commands
    VALID_COMMANDS = {"suggest", "resume", "cancel", "help", "status"}

    def __init__(self, prefix: str = DEFAULT_PREFIX):
        self.prefix = prefix

    def parse(self, command: str) -> Optional[ParsedCommand]:
        """Parse a slash command string.

        Args:
            command: Raw command string (e.g., "/agent-team suggest Add auth")

        Returns:
            ParsedCommand or None if invalid
        """
        if not command:
            return None

        # Strip leading slash if present
        command = command.strip()
        if command.startswith("/"):
            command = command[1:]

        # Extract the prefix and command
        pattern = rf"^{re.escape(self.prefix.lstrip('/'))}\s+(.+)$"
        match = re.match(pattern, command, re.IGNORECASE)

        if not match:
            # Try without prefix (for backward compatibility)
            parts = command.split(maxsplit=1)
            if parts[0].lower() not in self.VALID_COMMANDS:
                return None
            return ParsedCommand(
                command=parts[0].lower(),
                subcommand=None,
                args=parts[1] if len(parts) > 1 else "",
                raw=command,
            )

        remainder = match.group(1).strip()
        parts = remainder.split(maxsplit=1)

        cmd = parts[0].lower()
        if cmd not in self.VALID_COMMANDS:
            return None

        # Handle "help suggest" style subcommands
        subcommand = None
        if cmd == "help" and len(parts) > 1:
            subcommand = parts[1].lower()

        return ParsedCommand(
            command=cmd,
            subcommand=subcommand,
            args=parts[1] if cmd != "help" and len(parts) > 1 else "",
            raw=command,
        )

    def validate_args(self, command: str, args: str) -> tuple[bool, Optional[str]]:
        """Validate command arguments.

        Args:
            command: Command name
            args: Command arguments

        Returns:
            Tuple of (is_valid, error_message)
        """
        # suggest requires arguments
        if command == "suggest":
            if not args or not args.strip():
                return False, "Usage: /agent-team suggest <feature description>"
            if len(args) > 1000:
                return False, "Feature description must be under 1000 characters"

        return True, None
