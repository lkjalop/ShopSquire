FROM python:3.11-slim

ENV POETRY_VERSION=1.7.1 \
    POETRY_HTTP_TIMEOUT=120 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libzbar0 \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --retries 10 --timeout 120 poetry==${POETRY_VERSION}

WORKDIR /app

COPY pyproject.toml /app/
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

COPY src /app/src
COPY alembic.ini /app/
COPY alembic /app/alembic
COPY config /app/config
COPY db /app/db
COPY scripts /app/scripts
COPY README.md /app/

EXPOSE 8080

RUN chmod +x /app/scripts/docker_entrypoint.sh
RUN addgroup --system shopsquire && adduser --system --ingroup shopsquire shopsquire \
    && chown -R shopsquire:shopsquire /app

USER shopsquire

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
