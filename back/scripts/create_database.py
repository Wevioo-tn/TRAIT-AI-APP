"""Create the configured PostgreSQL database before running Alembic."""
import argparse
import os

from sqlalchemy import create_engine, make_url, text

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maintenance-db", default="postgres",
        help="Existing database to connect to for creation (default: postgres).",
    )
    args = parser.parse_args()
    # Match migrations/env.py, including its optional URL override.
    url = make_url(os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().database_url)
    if url.get_backend_name() != "postgresql" or not url.database:
        parser.error("Configure a PostgreSQL URL with a target database name.")

    engine = create_engine(
        url.set(database=args.maintenance_db), isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if exists:
                print(f"Database already exists: {url.database}")
                return
            name = connection.dialect.identifier_preparer.quote_identifier(url.database)
            connection.exec_driver_sql(f"CREATE DATABASE {name}")
            print(f"Created database: {url.database}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
