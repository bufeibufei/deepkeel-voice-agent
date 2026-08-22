FROM python:3.12-slim-bookworm

RUN sed -i 's|http://deb.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple uv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend ./backend
COPY frontend ./frontend
COPY travel_mcp ./travel_mcp
COPY tokens.css ./tokens.css

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
