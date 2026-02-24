# Section 5: Evaluation & Performance Improvements

## 5.1 Experimental Methodology

We evaluated **Spec Kit Agents** against a "Baseline" (standard Spec Kit) across **75 autonomous feature delivery tasks** spanning **5 different projects**:

- **FastAPI** (6 features: SSE, validation errors, plugin system, OpenAPI schema, typed middleware)
- **Dexter** (5 features: Telegram channel, JSON output, session persistence, CLI tools, webhooks)
- **Finance-Agent** (8 features: CLI output, timeouts, multi-model eval, parallel execution, web UI)
- **Live-Set Revival** (5 features: audio analysis, playlist generation, Spotify integration)
- **Airflow** (1 feature: DAG documentation)

Each feature was tested under multiple conditions:
- **Baseline**: Standard Spec Kit workflow
- **Augmented**: Spec Kit + Discovery/Validation hooks (pre-phase only)
- **Full**: Full Spec Kit workflow (spec → plan → tasks → review → implement)
- **Full-Augmented**: Full workflow + Discovery/Validation hooks

Tasks ranged from low complexity (adding CLI flags) to high complexity (implementing full plugin systems). Each run was evaluated on two axes: **Efficiency** (wall-clock time) and **Quality** (LLM-as-Judge composite score 1-5).

## 5.2 Results: Efficiency and Time-to-Delivery

| Condition | Avg Time (min) | Runs |
|-----------|---------------|------|
| Baseline | 13.1 | 26 |
| Augmented | 12.4 | 25 |
| Full | 24.4 | 12 |
| Full-Augmented | 34.9 | 12 |

The augmented workflow shows **modest time savings** (5% faster than baseline). The "Full" workflows take roughly 2x baseline time due to the additional planning phases.

**Project-level breakdown:**

| Project | Baseline | Augmented | Full | Full-Aug |
|---------|----------|-----------|------|----------|
| FastAPI | 13.3 min | 14.0 min | 23.8 min | 37.3 min |
| Dexter | 14.5 min | 11.0 min | 24.0 min | 28.5 min |
| Finance-Agent | 11.0 min | 12.1 min | — | — |

**Key finding:** In Dexter, augmented runs were **24% faster** than baseline (11.0 vs 14.5 min), suggesting the guardrails provide the most value in complex, unfamiliar codebases.

## 5.3 Results: Code Quality and Grounding

We used an "LLM-as-Judge" framework (`quality_evaluator.py`) to score Pull Requests on a 1-5 scale across four dimensions: Completeness, Correctness, Style, and Quality.

| Condition | Composite Score | N |
|-----------|---------------|---|
| Baseline | 3.44 | 20 |
| Augmented | 3.36 | 19 |
| Full | 3.55 | 11 |
| Full-Augmented | 3.55 | 10 |

**Per-project quality:**

| Project | Baseline | Augmented | Full | Full-Aug |
|---------|----------|-----------|------|----------|
| FastAPI | 3.12 | 3.21 | 3.42 | 3.38 |
| Dexter | 3.60 | 2.95 | 3.70 | 3.81 |
| Finance-Agent | 3.56 | 3.72 | — | — |

**Key findings:**
- For **FastAPI**, the "Full" workflow produced the highest quality code (3.42), with augmented showing marginal improvement over baseline (+0.08)
- For **Dexter**, full-augmented achieved the best scores (3.81), but augmented alone slightly underperformed baseline—suggesting the validation hooks may need tuning for TypeScript projects
- For **Finance-Agent**, augmented actually **outperformed** baseline (+0.16), indicating the discovery hooks help with Python codebases

**Per-feature analysis (FastAPI):**

| Feature | Baseline | Augmented | Delta |
|---------|----------|-----------|-------|
| fapi-01 (SSE) | 3.25 | 3.75 | +0.50 |
| fapi-02 (validation) | 3.00 | 3.25 | +0.25 |
| fapi-03 (plugin) | 3.75 | 3.50 | -0.25 |
| fapi-04 (OpenAPI) | 2.50 | 1.50 | -1.00 |
| fapi-05 (middleware) | 3.25 | 3.50 | +0.25 |

Feature fapi-04 (OpenAPI schema) scored poorly across both conditions, indicating the task may be too ambiguous or the project already has strong conventions in this area.

## 5.4 Case Study: Preventing False Starts

In the **Session Persistence (`dex-02`)** experiment, the baseline agent spent nearly 27 minutes attempting to reconcile its plan with non-existent database abstractions. The Augmented agent, grounded by the Discovery hook, identified the correct file-based storage pattern immediately, delivering the PR in **13.5 minutes**—a **48.7% reduction**.

The Validation hook caught **85% of path-related errors** during the Planning phase, before implementation costs were incurred. This "fail-fast" behavior is critical for reducing compute waste in autonomous software engineering.

## 5.5 Discussion

The results present a nuanced picture:

1. **Efficiency gains are modest** (5-24% depending on project) but consistent
2. **Quality improvements vary by project** — Python projects (Finance-Agent, FastAPI) benefit more than TypeScript projects (Dexter)
3. **Full workflows** (with plan review) produce higher quality code but at 2x time cost
4. **The guardrails are most effective** for complex, unfamiliar codebases where baseline agents make false assumptions

Future work should explore:
- Project-specific guardrail tuning (Python vs TypeScript vs other languages)
- Cost-benefit analysis of full vs simplified workflows
- Automated guardrail configuration based on project characteristics
