FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    pydantic-settings \
    sqlmodel \
    asyncpg \
    redis \
    openai \
    langgraph \
    langchain \
    langchain-openai \
    langsmith \
    httpx \
    tenacity \
    structlog \
    python-dotenv \
    pygments \
    gitpython \
    pytest \
    pytest-asyncio \
    pytest-cov \
    ruff

COPY . .

RUN mkdir -p results sample_code

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
