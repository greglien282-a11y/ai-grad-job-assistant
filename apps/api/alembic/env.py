from alembic import context
from sqlalchemy import create_engine, pool

from app.db import database_url
from app.models import Base

config = context.config

if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get("connection")

    def migrate(connection):
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

    if supplied is not None:
        migrate(supplied)
    else:
        engine = create_engine(database_url(), poolclass=pool.NullPool, hide_parameters=True)
        with engine.connect() as connection:
            migrate(connection)
        engine.dispose()
