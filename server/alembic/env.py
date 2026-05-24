from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings

config = context.config
# configparser в alembic интерпретирует одиночный `%` как начало interpolation
# (`%(name)s`), что ломается на URL-encoded паролях вида `%5E%24...`. Удваиваем
# `%` → `%%` — это конвенция configparser'а для литерального процента.
config.set_main_option("sqlalchemy.url", settings.alembic_database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
