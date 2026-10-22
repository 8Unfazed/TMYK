from logging.config import fileConfig
import os
from dotenv import load_dotenv
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url
from app.models import Base

config = context.config
load_dotenv()
if config.config_file_name:
    fileConfig(config.config_file_name)
database_url = make_url(os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url")))
if database_url.drivername in ("postgres", "postgresql"):
    database_url = database_url.set(drivername="postgresql+psycopg")
config.set_main_option("sqlalchemy.url", database_url.render_as_string(hide_password=False).replace("%", "%%"))
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
