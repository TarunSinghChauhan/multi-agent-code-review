# Multi-Agent Code Review System

A LangGraph pipeline for automated code review. Specialized agents analyze code quality and security, propose fixes for critical issues, and a merger builds one ranked report, all under an enforced cost budget.

**Live demo:** https://multi-agent-code-review-tcrz.onrender.com/
Paste Python code or run the built-in sample with intentional vulnerabilities. The demo is limited to 30 reviews per day and 6,000 characters per submission. It runs on a free tier, so the first load may be slow.

## What it does

| Agent | Responsibility |
| --- | --- |
| **Static Analysis Agent** | AST parsing plus LLM-based code quality analysis (mutable defaults, bare excepts, complexity, naming) |
| **Security Agent** | OWASP-style pattern scan (regex + AST, no API cost) plus an LLM audit: hardcoded secrets, injection risks, dangerous calls such as `eval()` |
| **Fix Proposal Agent** | Generates concrete code fixes for critical issues only |
| **Merger Agent** | Deduplicates findings, ranks by severity, and builds the final report |

## Architecture

```
Code input (API or web UI)
         │
         ▼
┌──────────────────────────┐
│   LangGraph Orchestrator  │
│   (cost budget enforcer)  │
└────────────┬─────────────┘
             │ parallel dispatch
    ┌────────┴─────────┐
    │                  │
┌───▼────┐      ┌──────▼──────┐
│ Static │      │  Security   │
│Analysis│      │   Agent     │
│ Agent  │      │ OWASP scan  │
└───┬────┘      └──────┬──────┘
    │                  │
    └────────┬─────────┘
             │ all issues merged
             ▼
    ┌────────────────┐
    │  Fix Proposal  │
    │     Agent      │
    │ (critical only)│
    └────────┬───────┘
             │
             ▼
    ┌────────────────┐
    │  Merger Agent  │
    │ dedup + rank   │
    └────────┬───────┘
             │
             ▼
    Structured Review Report
```

The static analysis and security agents run in parallel. Fix proposals run after both finish, so they can target the critical issues either agent found.

### Design decisions

- **Typed state between agents.** Agents share a typed LangGraph state (`PRState` in `src/agents/state.py`), so each one reads and writes a defined structure instead of free-form text. This reduces silent failures when an LLM returns malformed output.
- **Cheap checks first.** The pattern-based scanner costs nothing to run and catches the well-known cases. The LLM is used for what patterns can't catch.
- **A cost budget is enforced by the orchestrator.** Each review runs under a per-review spending limit, so a review can't run up an unbounded bill.
- **Fixes only for critical issues.** The Fix Proposal Agent is the most expensive step, so it runs only where it matters most.

## Sample result

Output from the built-in sample (`vulnerable_code.py`, which contains intentional vulnerabilities):

| Metric | Value |
| --- | --- |
| Verdict | Critical issues found, do not merge |
| Total issues | 11 |
| Critical | 3 |
| High | 3 |
| Medium | 5 |
| Low | 0 |
| Static Analysis findings | 2 (mutable default argument, bare `except`) |
| Security findings | 9 (including a hardcoded password) |

Abridged example of the API response (field values are illustrative):

```json
{
  "total_issues": 11,
  "severity_counts": { "critical": 3, "high": 3, "medium": 5, "low": 0 },
  "total_cost_usd": 0.0,
  "review_summary": "CRITICAL ISSUES FOUND — Do not merge ...",
  "fix_proposals": [
    {
      "issue_title": "Hardcoded Password",
      "original_code": "password = \"admin123\"",
      "fixed_code": "password = os.environ.get('APP_PASSWORD')",
      "explanation": "Moved credential to environment variable"
    }
  ]
}
```

## Quickstart

### Prerequisites

- Docker Desktop
- An [OpenRouter](https://openrouter.ai) API key (free credits available)
- A [LangSmith](https://smith.langchain.com) API key (free tier)

### 1. Setup

```bash
git clone https://github.com/TarunSinghChauhan/multi-agent-code-review
cd multi-agent-code-review
cp .env.example .env
# add your API keys to .env
```

### 2. Launch

```bash
docker compose up --build
```

API docs: <http://localhost:8001/docs>

### 3. Run a demo review (built-in vulnerable code)

```bash
curl -X POST http://localhost:8001/reviews/submit/sample
```

### 4. Submit your own code

```bash
curl -X POST http://localhost:8001/reviews/submit \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "app.py",
    "language": "python",
    "code": "your code here"
  }'
```

### 5. Get results

```bash
curl http://localhost:8001/reviews/results/{job_id}
```

## Tech stack

`Python 3.12` · `LangGraph` · `FastAPI` · `OpenRouter API` · `LangSmith` · `PostgreSQL` · `Redis` · `Docker`

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Project structure

```
multi-agent-code-review/
├── src/
│   ├── agents/
│   │   ├── state.py            # LangGraph PRState schema
│   │   ├── static_analysis.py  # AST + LLM quality analysis
│   │   ├── security.py         # OWASP pattern scan + LLM audit
│   │   ├── fix_proposal.py     # Code fix generator
│   │   ├── merger.py           # Dedup + rank + summarize
│   │   └── orchestrator.py     # LangGraph graph builder
│   ├── api/routers/            # FastAPI endpoints
│   └── core/                   # Config, DB, logging
├── sample_code/                # Example files for the demo
├── tests/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Limitations

- **Python only.** The demo and sample target Python code.
- **Pattern scanning has limits.** Regex and AST checks catch known patterns and miss novel or context-dependent vulnerabilities. The LLM audit helps but can also miss or misjudge issues.
- **LLM output is not guaranteed correct.** Proposed fixes should be reviewed by a human before merging.
- **Demo limits.** The public demo is rate-limited and runs on free-tier infrastructure, so it may be slow or temporarily unavailable.

## Roadmap

- [ ] GitHub pull request integration
- [ ] Support for more languages
- [ ] A benchmark set of vulnerable files with known issue counts, to measure detection accuracy
- [ ] Per-agent cost breakdown in the report

## License

MIT
