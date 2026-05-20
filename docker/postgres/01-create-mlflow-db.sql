-- Создаётся при первом старте postgres-контейнера (init script monteapri в
-- /docker-entrypoint-initdb.d). Если volume уже есть — этот файл игнорируется,
-- БД создаётся вручную: docker exec brainscan_postgres createdb -U brainscan mlflow
CREATE DATABASE mlflow OWNER brainscan;
