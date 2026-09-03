import logging

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import settings


logger = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


def _sqlite_literal(column) -> str | None:
    """Render a column's default as a SQLite literal, or None if it has no usable default."""
    default = getattr(column, "default", None)
    value = getattr(default, "arg", None) if default is not None else None
    if callable(value):
        return None
    if value is None:
        return "NULL" if column.nullable else None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def ensure_schema() -> None:
    """Add columns that exist in the models but not yet in an older database.

    ``create_all`` creates missing tables but never alters existing ones, so an
    install that predates a new field would fail on every query touching it.
    This only ever runs ``ALTER TABLE ... ADD COLUMN``: nothing is dropped,
    renamed, or retyped, so it cannot lose data. Anything more involved belongs
    in an Alembic revision.
    """
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as connection:
        # Reflect on the same connection that performs the ALTERs. Inspecting
        # through the engine can hand back a cached or pooled view of the schema
        # that no longer matches, which then re-adds a column that already exists.
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())

        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present or column.primary_key:
                    continue
                literal = _sqlite_literal(column)
                if literal is None and not column.nullable:
                    logger.warning(
                        "Cannot add %s.%s automatically: it is NOT NULL with no static default.",
                        table.name, column.name,
                    )
                    continue
                column_type = column.type.compile(engine.dialect)
                clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'
                if literal is not None:
                    clause += f" DEFAULT {literal}"
                connection.execute(text(clause))
                logger.info("Added missing column %s.%s", table.name, column.name)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_schema()


def get_session():
    with Session(engine) as session:
        yield session
