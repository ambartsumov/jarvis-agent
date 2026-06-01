# PDS-Ultimate v2 — Docker
FROM python:3.12-slim AS runtime

LABEL version="2.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=Asia/Ashgabat \
    WHISPER_DEVICE=cpu \
    STT_ENGINE=vosk \
    STT_LAZY_LOAD=true \
    STT_UNLOAD_AFTER=true \
    STT_MAX_VOICE_SECONDS=90 \
    MEMORY_TOKEN_BUDGET=900 \
    MEMORY_LLM_SUMMARIZE=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pds_ultimate/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY pds_ultimate/ /app/pds_ultimate/
COPY start_agent.sh /app/start_agent.sh

RUN mkdir -p \
    /app/pds_ultimate/data \
    /app/pds_ultimate/data/agentmemory \
    /app/pds_ultimate/data/vosk_models \
    /app/pds_ultimate/logs \
    /app/pds_ultimate/credentials

RUN groupadd -r pds && useradd -r -g pds -d /app pds && chown -R pds:pds /app
USER pds

HEALTHCHECK --interval=60s --timeout=10s --start-period=45s --retries=3 \
    CMD python -c "from pds_ultimate.core.agent import agent; print(agent.name)" || exit 1

CMD ["python", "-m", "pds_ultimate.main"]
