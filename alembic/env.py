from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import create_engine

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
import sys
sys.path.insert(0, os.getcwd())
from app.base import Base

target_metadata = Base.metadata

# Prefer an explicit sync URL for Alembic when available (container-friendly)
db_host = os.getenv("DB_HOST", "db")
db_name = os.getenv("DB_NAME", "n8n_popularity")
db_user = os.getenv("DB_USER", "postgres")
db_pass = os.getenv("DB_PASS", "postgres")
sync_url = os.getenv("ALEMBIC_SYNC_URL") or f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
config.set_main_option("sqlalchemy.url", sync_url)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
