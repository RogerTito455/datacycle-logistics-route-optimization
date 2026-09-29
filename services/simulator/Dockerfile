# The simulator with the generator it depends on, in their pinned environment (services/simulator/uv.lock).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY services/generator services/generator
COPY services/simulator services/simulator
RUN uv sync --project services/simulator --frozen --no-dev

ENV PATH=/app/services/simulator/.venv/bin:$PATH
ENTRYPOINT ["llobregat-simulator"]
CMD ["--help"]
