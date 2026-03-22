import tempfile
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.config as config_module
from alembic import command


def test_alembic_upgrade_head_on_fresh_sqlite_db():
    original_database_url = config_module.settings.database_url
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fresh.db"
            database_url = f"sqlite:///{db_path}"

            config_module.settings.database_url = database_url

            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")

            engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False},
            )
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())

            assert {"secrets", "pow_challenges"}.issubset(tables)
    finally:
        config_module.settings.database_url = original_database_url
