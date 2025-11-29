import os

from databases import Database

DATABASE_URL = os.environ["DATABASE_URL"]

database = Database(DATABASE_URL)


async def connect() -> None:
    await database.connect()


async def disconnect() -> None:
    await database.disconnect()
