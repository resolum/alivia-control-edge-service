from contextlib import contextmanager
from datetime import datetime, timezone
from peewee import DateTimeField, Model, SqliteDatabase

database = SqliteDatabase(None, pragmas={"foreign_keys": 1, "journal_mode": "wal"})

class BaseModel(Model):
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    class Meta:
        database = database

def initialize_database(path: str, models: list[type[Model]]) -> None:
    if not database.is_closed():
        database.close()
    database.init(path)
    database.connect(reuse_if_open=True)
    database.create_tables(models, safe=True)

@contextmanager
def unit_of_work():
    with database.atomic() as transaction:
        yield transaction
