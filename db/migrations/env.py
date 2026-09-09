"""Alembic migration environment.

Two deliberate departures from the `alembic init` boilerplate:

1. `target_metadata` points at `db.migrations.models.Base.metadata` — the
   ORM models in `db/migrations/models.py` are the single source of truth
   for schema shape. `alembic revision --autogenerate` diffs against those
   models, not against a second hand-maintained schema description.
2. The connection URL comes from `src.config.get_settings().database_url`,
   not from `alembic.ini`'s `sqlalchemy.url` or a hardcoded string — the
   same `.env`/`DATABASE_URL` that the running application uses. Running
   `alembic upgrade head` against the wrong DB because someone forgot to
   edit `alembic.ini` is exactly the kind of reproducibility gap blueprint
   §9 exists to avoid.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.migrations.models import Base
from src.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override whatever (if anything) is in alembic.ini with the app's actual
# configured database — see module docstring.
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (`alembic upgrade
    head --sql`). Used for review before applying to a shared/prod DB, or
    when generating a plain .sql file for a DBA to run.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live DB connection — the normal path for
    local dev (SQLite) and CI.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite can't ALTER most constraints in place; batch mode
            # rebuilds the table under the hood instead. Harmless no-op on
            # Postgres, required for SQLite (README §5's dev DB).
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()