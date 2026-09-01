FROM denoland/deno:bin-2.9.6 AS deno

FROM python:3.12-slim AS pot-builder

COPY --from=deno /deno /usr/local/bin/deno
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates git && \
    git clone --depth 1 --branch 1.3.1 \
      https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil && \
    rm -rf /var/lib/apt/lists/* /opt/bgutil/.git
WORKDIR /opt/bgutil/server
RUN deno install --allow-scripts=npm:canvas --frozen

FROM python:3.12-slim

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser
COPY --from=pot-builder --chown=appuser:appuser /opt/bgutil /opt/bgutil

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/downloads /home/appuser/.cache/bgutil-ytdlp-pot-provider && \
    chown -R appuser:appuser /app/downloads /home/appuser/.cache

EXPOSE 7860
ENV HOST=0.0.0.0
ENV PORT=7860
ENV RECLIP_TRIM_BACKEND=disabled
USER appuser
RUN deno run \
      --allow-env --allow-net \
      --allow-ffi=/opt/bgutil/server/node_modules \
      --allow-write=/home/appuser/.cache/bgutil-ytdlp-pot-provider \
      --allow-read=/home/appuser/.cache/bgutil-ytdlp-pot-provider,/opt/bgutil/server/node_modules \
      /opt/bgutil/server/src/generate_once.ts --version
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "4", "--timeout", "360", "app:app"]
