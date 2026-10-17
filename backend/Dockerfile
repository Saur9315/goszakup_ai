# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim AS model

ARG MODEL_URL=https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3
ARG MODEL_DIR=/opt/models/multilingual-e5-small-614241f6
ADD --checksum=sha256:dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88 \
    ${MODEL_URL}/onnx/model_qint8_avx512_vnni.onnx ${MODEL_DIR}/model_qint8_avx512_vnni.onnx
ADD --checksum=sha256:0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39 \
    ${MODEL_URL}/tokenizer.json ${MODEL_DIR}/tokenizer.json
RUN chmod -R a+rX /opt/models


FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=model /opt/models /opt/models
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_DIR=/opt/models
USER app
EXPOSE 8000

ENTRYPOINT ["goszakup"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
