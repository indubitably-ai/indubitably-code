FROM python:3.13-slim

ENV UV_SYSTEM_PYTHON=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --upgrade pip && pip install uv

WORKDIR /app
COPY . /app

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["indubitably-agent"]
CMD ["--help"]
