# Section 6: Demonstration Artifact
We demonstrate **Spec Kit Agents** as a live, multi-agent collaboration system integrated with **Mattermost**. The demonstration artifact features:
1.  **Human-in-the-Loop Interaction**: A user requests a feature via a chat slash-command (`/suggest`).
2.  **State Machine Visualization**: Real-time tracking of the orchestrator's state transitions through the Spec Kit phases.
3.  **The "Prober" in Action**: A background visualization showing the "prober" agent executing `grep`, `glob`, and `bash` tools to discover codebase context before the Dev Agent writes its first specification.
4.  **Verification Checkpoints**: A demonstration of the Validation hook catching a hallucinated module reference in a generated `PLAN.md` and forcing a correction before implementation.
5.  **Final Delivery**: The automated generation and submission of a lint-clean, test-passing Pull Request to a GitHub repository.
