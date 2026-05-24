# Минимальный MLflow tracking server. python:3.12-slim уже закэширован на dev VPS
# (его дёргает brainscan-server) → собирается за 30 сек без Docker Hub rate-limit.
# Backend store: SQLite в volume `mlflow_data`. Artifact store: S3 (TimeWebCloud).
# Версия mlflow закреплена, чтобы schema БД не дрейфовала между деплоями.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MLFLOW_HOME=/mlflow

RUN pip install --no-cache-dir \
    "mlflow==2.19.0" \
    "boto3>=1.35" \
    "psycopg2-binary>=2.9"

WORKDIR /mlflow
EXPOSE 5000

# --serve-artifacts + --artifacts-destination=s3://… разводит metadata (SQLite) и
# артефакты (S3): MLflow сам подписывает S3-запросы по AWS_* env-vars. Воркеры
# складывают через MLflow API → не нужны S3-креды на стороне воркера.
# Shell-form CMD, чтобы ${MLFLOW_S3_*} подставлялись из env.
CMD mlflow server \
      --host 0.0.0.0 \
      --port 5000 \
      --backend-store-uri sqlite:////mlflow/mlflow.db \
      --artifacts-destination "s3://${MLFLOW_S3_BUCKET}/${MLFLOW_S3_PREFIX}" \
      --serve-artifacts
