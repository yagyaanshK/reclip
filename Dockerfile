FROM denoland/deno:bin-2.9.6 AS deno

FROM python:3.12-slim

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/downloads && chown appuser:appuser /app/downloads

EXPOSE 7860
ENV HOST=0.0.0.0
ENV PORT=7860
ENV RECLIP_TRIM_BACKEND=disabled
USER appuser
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "4", "--timeout", "360", "app:app"]
