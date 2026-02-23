# Section 2: Background - Spec-Driven Development with Spec Kit

## 2.1 The SDD Paradigm
Spec-Driven Development (SDD) is a software engineering methodology that prioritizes specifications as the primary source of truth, treating code as a derived or verified artifact. In the age of Large Language Models (LLMs), SDD provides a structured interface that reduces ambiguity and enhances the reliability of AI-generated code. Spec Kit defines a spectrum of SDD rigor:
- **Spec-First**: Specs guide initial development but may drift over time.
- **Spec-Anchored**: Specs and code are kept in sync via automated verification.
- **Spec-as-Source**: Code is entirely generated from executable specifications.

## 2.2 The Spec Kit Workflow
Spec Kit provides a standardized, command-based workflow designed for AI-native development:
1.  **`/speckit.specify`**: Generates a `SPEC.md` defining the "What" (requirements, constraints, and success criteria).
2.  **`/speckit.plan`**: Generates a `PLAN.md` defining the "How" (architecture, file changes, and dependencies).
3.  **`/speckit.tasks`**: Generates a `TASKS.md` containing an executable checklist of implementation steps.
4.  **`/speckit.implement`**: Executes the tasks to produce the final code and tests.

By enforcing this four-phase reasoning process, Spec Kit ensures that the agent "thinks" before it "codes," creating a transparent audit trail of technical decisions.
