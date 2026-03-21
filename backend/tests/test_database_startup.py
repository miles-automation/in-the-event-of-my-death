"""Tests for database initialization and startup behavior.

These tests verify that the application handles database state correctly,
particularly when migrations haven't been run.
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect


class TestDatabaseStartup:
    """Tests for database initialization at startup."""

    def test_check_database_tables_raises_on_missing_tables(self):
        """
        Test that check_database_tables() raises RuntimeError when tables are missing.

        This verifies the fix for Issue #31 where running `make dev` without
        `make migrate` causes: sqlite3.OperationalError: no such table: pow_challenges
        """
        from app.main import check_database_tables

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            empty_db_path = tmp.name

        try:
            # Create an empty database (no tables)
            empty_engine = create_engine(
                f"sqlite:///{empty_db_path}",
                connect_args={"check_same_thread": False},
            )

            # Verify it's empty
            inspector = inspect(empty_engine)
            assert len(inspector.get_table_names()) == 0

            # Temporarily patch the engine used by check_database_tables
            import app.main as main_module

            original_engine = main_module.engine
            main_module.engine = empty_engine

            try:
                with pytest.raises(RuntimeError) as exc_info:
                    check_database_tables()

                error_message = str(exc_info.value)
                assert "Database tables missing" in error_message
                assert "make migrate" in error_message
            finally:
                main_module.engine = original_engine

        finally:
            if os.path.exists(empty_db_path):
                os.unlink(empty_db_path)

    def test_check_database_tables_passes_with_all_tables(self, db_session):
        """
        Test that check_database_tables() passes when all tables exist.
        """
        import app.main as main_module
        from app.main import check_database_tables

        # Use the test session's engine which has all tables created
        original_engine = main_module.engine
        main_module.engine = db_session.get_bind()

        try:
            # Should not raise any exception
            check_database_tables()
        finally:
            main_module.engine = original_engine

    def test_required_tables_exist_after_setup(self, db_session):
        """
        Test that the required tables exist after proper setup.
        """
        engine = db_session.get_bind()
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        required_tables = {"secrets", "pow_challenges"}
        assert required_tables.issubset(tables), (
            f"Missing required tables. Expected: {required_tables}, Found: {tables}"
        )
