# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added
- **Dev-Agent Mention Handling**: Implementation questions with `@dev-agent` mention now route to Dev Agent instead of falling back to PM Agent. Routing logic includes precedence handling for multiple mentions and proper logging of routing decisions.

### Fixed
- Fixed routing for `@dev-agent` mentions that previously returned "coming soon" message

## [0.1.0] - 2026-02-20

### Added
- Initial release with PM Agent and Dev Agent workflow orchestration
- Mattermost bot integration for feature suggestions
- Redis state persistence support
