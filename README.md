# Multi-Agent Code Review System

> Autonomous code review pipeline using LangGraph — 3 specialized AI agents analyze security, code quality, and generate fixes in parallel.

Built to solve the real engineering problem: **senior engineers spending 40% of their time on repetitive code review tasks.**

---

## What This Does

| Agent | Responsibility |
|---|---|
| **Static Analysis Agent** | AST parsing, complexity, naming, code quality |
| **Security Agent** | OWASP Top 10, hardcoded secrets, injection risks |
| **Fix Proposal Agent** | Generates actual code fixes for critical issues |
| **Merger Agent** | Deduplicates, ranks by severity, builds final report |

---

## Architecture

```
GitHub PR / Code Input
         │
         ▼
┌─────────────────────────┐
│   LangGraph Orchestrator │
│   (cost budget enforcer) │
└────────────┬────────────┘
             │ parallel dispatch
    ┌────────┴─────────┐
    │                  │
┌───▼────┐      ┌──────▼──────┐
│ Static │      │  Security   │
│Analysis│      │   Agent     │
│ Agent  │      │OWASP Top 10 │
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

---

## Quickstart

### Prerequisites
- Docker Desktop
- OpenRouter API key (openrouter.ai — free credits)
- LangSmith API key (smith.langchain.com — free)

### 1. Setup
```bash
git clone https://github.com/TarunSinghChauhan/multi-agent-code-review
cd multi-agent-code-review
cp .env.example .env
# Add your API keys to .env
```

### 2. Launch
```bash
docker compose up --build
```

API runs at: **http://localhost:8001/docs**

### 3. Run a Demo Review (built-in vulnerable code)
```bash
curl -X POST http://localhost:8001/reviews/submit/sample
```

### 4. Submit Your Own Code
```bash
curl -X POST http://localhost:8001/reviews/submit \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "app.py",
    "language": "python",
    "code": "your code here"
  }'
```

### 5. Get Results
```bash
curl http://localhost:8001/reviews/results/{job_id}
```

---

## Sample Output

```json
{
  "total_issues": 12,
  "severity_counts": {
    "critical": 3,
    "high": 4,
    "medium": 3,
    "low": 2
  },
  "total_cost_usd": 0.0023,
  "review_summary": "🔴 CRITICAL ISSUES FOUND — Do not merge\n\n- [CRITICAL] Line 8: Hardcoded Password\n- [CRITICAL] Line 9: Hardcoded API Key\n- [HIGH] Line 23: Dangerous eval() Usage",
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

---

## Tech Stack

`Python 3.12` · `LangGraph` · `FastAPI` · `OpenRouter API` · `LangSmith` · `PostgreSQL` · `Redis` · `Docker`

---

## Running Tests
```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Project Structure

```
p2-code-review/
├── src/
│   ├── agents/
│   │   ├── state.py          # LangGraph PRState schema
│   │   ├── static_analysis.py # AST + LLM quality analysis
│   │   ├── security.py        # OWASP pattern scan + LLM audit
│   │   ├── fix_proposal.py    # Code fix generator
│   │   ├── merger.py          # Dedup + rank + summarize
│   │   └── orchestrator.py    # LangGraph graph builder
│   ├── api/routers/           # FastAPI endpoints
│   └── core/                  # Config, DB, logging
├── sample_code/               # Example files for demo
├── tests/
└── docker-compose.yml
```
