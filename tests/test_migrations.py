import os
import subprocess
import sys
import unittest
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
import sqlalchemy as sa
from psycopg import sql

from incidentlab.db.tables import metadata


class MigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_on_fresh_postgres_database(self) -> None:
        admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL")
        if not admin_url:
            self.skipTest("Set TEST_DATABASE_ADMIN_URL to run the PostgreSQL migration check")
        name = f"incidentlab_migration_{uuid.uuid4().hex[:12]}"
        parts = urlsplit(admin_url)
        database_url = urlunsplit((parts.scheme, parts.netloc, f"/{name}", "", ""))
        sqlalchemy_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        environment = {**os.environ, "DATABASE_URL": sqlalchemy_url}
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            try:
                subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    check=True,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                engine = sa.create_engine(sqlalchemy_url)
                try:
                    inspector = sa.inspect(engine)
                    self.assertEqual(
                        set(metadata.tables) | {"alembic_version"},
                        set(inspector.get_table_names()),
                    )
                    self.assertEqual(
                        {column.name for column in metadata.tables["incident_runs"].columns},
                        {column["name"] for column in inspector.get_columns("incident_runs")},
                    )
                finally:
                    engine.dispose()
                subprocess.run(
                    [sys.executable, "-m", "alembic", "downgrade", "base"],
                    check=True,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                engine = sa.create_engine(sqlalchemy_url)
                try:
                    self.assertFalse(
                        set(metadata.tables) & set(sa.inspect(engine).get_table_names())
                    )
                finally:
                    engine.dispose()
            finally:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
