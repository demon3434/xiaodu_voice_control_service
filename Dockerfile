FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN mkdir -p /data

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

EXPOSE 8129

CMD ["sh", "-c", "python -m xiaodu_voice_control.bootstrap && uvicorn xiaodu_voice_control.app:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8129}"]
