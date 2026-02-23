# Section 3: System Architecture - Spec Kit Agents

## 3.1 Orchestration and State Machine
**Spec Kit Agents** is built around a centralized Python-based **Orchestrator** that manages the lifecycle of a feature delivery. The Orchestrator drives a formal state machine that maps directly to the Spec Kit phases, but adds critical governance and communication layers:
- **INIT**: Environment validation and configuration loading.
- **PM_SUGGEST**: The Product Manager (PM) Agent analyzes the project's PRD and suggests a prioritized feature.
- **REVIEW**: A Human-in-the-Loop (HITL) checkpoint via Mattermost for approval of the feature suggestion.
- **DEV_SPECIFY / DEV_PLAN / DEV_TASKS**: Execution of the Spec Kit reasoning phases.
- **PLAN_REVIEW**: A second HITL checkpoint where the human reviews the technical plan before implementation begins.
- **DEV_IMPLEMENT**: The implementation phase, where the Dev Agent executes tasks and can interactively ask the PM Agent for clarification.
- **CREATE_PR**: Automated creation of a GitHub Pull Request from an isolated git worktree.

## 3.2 Multi-Agent Collaboration via Mattermost
The system employs a dual-bot identity on a self-hosted Mattermost server to provide clear attribution:
- **PM Bot**: Acts as the interface for product requirements and architectural guidance.
- **Dev Bot**: Acts as the interface for technical implementation and progress reporting.
This chat-based interface allows human operators to observe agent reasoning in real-time, intervene at checkpoints, and provide feedback through a familiar collaboration tool.

## 3.3 Distributed Execution with Redis Streams
To support high-throughput environments, the system can operate in a **Coordinator-Worker** mode. The Orchestrator publishes approved features to a **Redis Stream** (`feature-requests`), where a pool of independent workers picks up tasks. Each worker operates in a clean, isolated environment with its own git worktree and state persistence, allowing multiple features to be implemented in parallel while maintaining a consistent global state.
