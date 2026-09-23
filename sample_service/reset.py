"""Recreate the sample checkout database with known inventory."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def reset_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("DROP TABLE IF EXISTS inventory")
            connection.execute(
                "CREATE TABLE inventory (sku TEXT PRIMARY KEY, quantity INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO inventory (sku, quantity) VALUES (?, ?)", ("widget", 10)
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    reset_database(args.database)
    print(f"Reset {args.database}")


if __name__ == "__main__":
    main()
