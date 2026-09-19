# syntax=docker/dockerfile:1
#
# MLflow tracking-server. Bruger sin egen SQLite-fil i et navngivet volume som
# backend store, adskilt fra applikationens PostgreSQL-database (se
# docs/adr/0004-mlflow-observability.md) — observability-data og
# applikations-state deler bevidst ikke database.

FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow==2.* && \
    groupadd --system mlflow && useradd --system --gid mlflow --home-dir /mlflow mlflow

RUN mkdir -p /mlflow/backend /mlflow/artifacts && chown -R mlflow:mlflow /mlflow

USER mlflow
WORKDIR /mlflow

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/health', timeout=3).status == 200 else 1)"

CMD ["mlflow", "server", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/backend/mlflow.db", \
     "--default-artifact-root", "/mlflow/artifacts"]
