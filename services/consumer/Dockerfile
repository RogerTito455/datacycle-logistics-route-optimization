# The stream consumer in its pinned environment (services/consumer/uv.lock).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY services/consumer services/consumer
RUN uv sync --project services/consumer --frozen --no-dev

ENV PATH=/app/services/consumer/.venv/bin:$PATH
EXPOSE 8000
ENTRYPOINT ["llobregat-consumer"]
