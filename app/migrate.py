"""
Database migration tool.

Usage:
    uv run python -m app.migrate
"""

import os
import re
import sys
from pathlib import Path

import asyncpg


async def run_migrations() -> None:
    database_url = os.environ["DATABASE_URL"]
    migrations_dir = Path(__file__).parent.parent / "migrations"

    conn = await asyncpg.connect(database_url)

    try:
        # Create migrations tracking table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                version INTEGER UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Get latest applied version
        row = await conn.fetchrow("SELECT MAX(version) as version FROM _migrations")
        current_version = row["version"] or 0

        # Find migration files
        migration_pattern = re.compile(r"^(\d{4})_(.+)\.sql$")
        migrations = []

        for file in sorted(migrations_dir.iterdir()):
            match = migration_pattern.match(file.name)
            if match:
                version = int(match.group(1))
                name = match.group(2)
                if version > current_version:
                    migrations.append((version, name, file))

        if not migrations:
            print(f"Database is up to date (version {current_version})")
            return

        # Apply migrations
        for version, name, file in migrations:
            print(f"Applying migration {version:04d}_{name}...")
            sql = file.read_text()

            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _migrations (version, name) VALUES ($1, $2)",
                version,
                name,
            )

            print(f"  Applied {version:04d}_{name}")

        print(f"Migrations complete. Now at version {migrations[-1][0]}")

    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(run_migrations())
    except KeyError:
        print("Error: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
