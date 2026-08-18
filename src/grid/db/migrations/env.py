"""Alembic environment — wired to GRID settings.

The database URL comes from GRID_DATABASE_URL via src/grid/config.py (.env),
never from alembic.ini — no credentials in tracked files.
"""

from logging.config import fileConfig

from alembic import context

from grid.config import get_settings
from grid.db.engine import SCHEMAS, ensure_schemas, make_engine
from grid.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="ops",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # make_engine (not engine_from_config) so the layer schemas exist before any DDL
    # runs: CREATE SCHEMA on Postgres, ATTACH DATABASE on SQLite (ADR 0006).
    connectable = make_engine(config.get_main_option("sqlalchemy.url") or "")
    ensure_schemas(connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            # The alembic_version bookkeeping table lives in `ops` alongside the other
            # operational tables, not in the default schema.
            version_table_schema="ops",
            # Only manage the layer schemas; never touch anything else in the database.
            include_object=lambda obj, name, type_, reflected, compare_to: (
                getattr(obj, "schema", None) in SCHEMAS if type_ == "table" else True
            ),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
