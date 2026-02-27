FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN chmod +x orchestrator/*.py agent pm2-core

EXPOSE 8080

CMD ["python3", "orchestrator/api_server.py", "--host", "0.0.0.0", "--port", "8080"]
