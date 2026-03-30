# DB Backup Orchestrator - Dockerfile

← [Back to index](../README.md)

## Orchestrator Dockerfile

```dockerfile
FROM python:3.12-slim

# Install Docker CLI only (no daemon)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg openssl && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | \
      gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) \
      signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db_backup_orchestrator/ ./db_backup_orchestrator/
COPY entrypoint.py .

RUN mkdir -p /backups

ENTRYPOINT ["python", "entrypoint.py"]
```
