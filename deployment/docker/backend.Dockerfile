FROM python:3.12-slim-bookworm

ARG APP_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="AI Hackathon demo backend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY backend/ ./
COPY data/processed/releases/r3/ /app/data/processed/releases/r3/

# The legacy /api service needs its local BM25 indexes. Build them inside the
# image with both online provider keys explicitly disabled; no host index or
# credential is copied into the build context.
RUN rm -rf data/index \
    && mkdir -p data/index /var/lib/caseapi \
    && GEMINI_API_KEY='' GOOGLE_API_KEY='' \
       python -c "from src.build_index import build_all; build_all(use_vector=False)" \
    && chown -R app:app /var/lib/caseapi

USER app

EXPOSE 8000 8001

