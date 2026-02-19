"""Slash command handling for Mattermost."""

from src.slash_commands.handlers import CommandResult, SlashCommandHandler
from src.slash_commands.parser import CommandParser
from src.slash_commands.registry import SlashCommandRegistry

__all__ = ["CommandParser", "SlashCommandRegistry", "SlashCommandHandler", "CommandResult"]
