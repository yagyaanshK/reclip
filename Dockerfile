FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/downloads && chown -R appuser:appuser /app

USER appuser

EXPOSE 7860
ENV HOST=0.0.0.0
ENV PORT=7860
CMD ["python", "app.py"]
