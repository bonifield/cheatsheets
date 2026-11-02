# SQLAlchemy

[Documentation]

`uv add sqlalchemy psycopg2-binary`


## Imports

not in perfect PEP 8 compliance, but this order is somewhat useful
```
# standard library imports
from datetime import datetime, timedelta, timezone
import uuid
# third party
import polars as pl
# sqlalchemy core-style - not PEP-8 compliant, but useful order
from sqlalchemy import (
    MetaData,
    Column, Table, ForeignKey,
    Boolean, DateTime, Integer, String,
    create_engine,
    and_, or_,
    delete, insert, select, text,
    distinct, func, inspect,
)
# sqlalchemy orm-style - also not PEP-8 compliant
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, Session,
    mapped_column, relationship,
)
from sqlalchemy.ext.automap import automap_base
# dialect helpers
from sqlalchemy.dialects.postgresql import UUID, insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
```

## Connection Engines

adding `echo=True` to `create_engine()` will output all of the SQL commands executed behind the scenes

SQLite: `engine = create_engine("sqlite:///database.sqlite")`

PostgreSQL: `engine = create_engine("postgresql://user:password@host:5432/database")`

PostgreSQL explicitly using `psycopg2`: `engine = create_engine("postgresql+psycopg2://user:password@host:5432/database")`


## Creating Tables

### Core

create a `MetaData()` container object first
```
metadata = MetaData()

user_table = Table(
	"user",
	metadata,
	Column("user_id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
	Column("email", String(200), nullable=False, unique=True),
	Column("enabled", Boolean(), default=False, nullable=False),
	Column("created_at", DateTime(timezone=True)),
	Column("latest_login", DateTime(timezone=True)),
)

metadata.create_all(engine)
```

note `UUID(as_uuid=True)` is cross-platform but `sqlalchemy.dialects.postgresql.UUID` is specific to PostgreSQL

### ORM

create a `DeclarativeBase` object first

```
class Base(DeclarativeBase):
	pass

class User(Base):
	__tablename__ = "user"
	user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
	enabled: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
	created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	latest_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	# foreign key relationships
	user_prefs: Mapped["UserPrefs"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)

Base.metadata.create_all(engine)
```


## Connecting to an existing database

### Core

create `metadata` object, read entire schema ("reflect"), and load tables
```
metadata = MetaData()
metadata.reflect(bind=engine)
# access individual tables
user_table = metadata.tables["user"]
user_prefs_table = metadata.tables["user_prefs"]
```

targeted reflection for a single table
- don't need `metadata.reflect(bind=engine)` here
```
user_table = Table("user", metadata, autoload_with=engine)
```

### ORM

create declarative `Base` class, read entire schema ("reflect"), and build ORM classes
```
Base = automap_base()
Base.prepare(autoload_with=engine)
# access the reflected classes (mapped to table names)
User = Base.classes.user
UserPrefs = Base.classes.user_prefs
```


## Inspecting the database

table names via `inspect()`
```
inspect(engine).get_table_names()
```

table names via metadata
- core: `metadata = MetaData()`
- ORM: `metadata = Base.metadata`
```
for table in metadata.sorted_tables:
	print(table.name)
	# use .c instead of .columns (both work)
	print(table.c.keys())
	for column in table.c:
		print(column.name, column.type, repr(column.type))
	print()
```


## Drop tables

drop the table, and remove it from metadata

### Core

```
drop_this_table.drop(engine, checkfirst=True)
metadata.remove(drop_this_table)
```

### ORM

```
DropThisTable.__table__.drop(engine, checkfirst=True)
Base.metadata.remove(DropThisTable.__table__)
```


## Inserts

note `pg_insert` is an import alias created above, for PostgreSQL's specific `insert`

### Core

`with engine.begin() ...` **will auto-commit**
```
new_users = [
	{"email":"bob@local", ...

with engine.begin() as connection:
	stmt = pg_insert(user_table).values(new_users)
	stmt = stmt.on_conflict_do_nothing(index_elements=["email"])
	connection.execute(stmt)
```

### ORM

**does not auto-commit** (needs `session.commit()`)
```
new_users = [
	{"email":"bob@local", ...

with Session(engine) as session:
	stmt = pg_insert(user_table).values(new_users)
	stmt = stmt.on_conflict_do_nothing(index_elements=["email"])
	session.execute(stmt)
	session.commit()
```

**does auto-commit** (do not use `session.commit()`)
```
with Session(engine) as session:
	with session.begin():
		stmt = pg_insert(user_table).values(new_users)
		stmt = stmt.on_conflict_do_nothing(index_elements=["email"])
		session.execute(stmt)
```

in a loop, you may use `session.add(obj)` instead of creating whole statement objects
- for multiple objects, use `add_all([obj1, obj2])`
- all items must be fully instantiated ORM objects
```
with Session(engine) as session:
	for u in new_users:
		user_obj = User(...)
		session.add(user_obj)
	session.commit()
```


## Queries

| action or behavior | core style | ORM style |
| -- | -- | -- |
| sending a query | send `Table` objects | send class objects (`User` etc) |
| what returns | rows or single items | instances of class objects |
| relationships | write manual joins | use attributes created using `relationship` |
| state tracking | none | Session tracks changes and can auto-commit |

### Core

the metadata knows the column names, so you may access data like a tuple or dict mapping
- this isn't actually accessing classful attributes, but rather using `__getattr__` and the metadata for convenience
```
stmt = select(user_table).where(user_table.c.email == "bob@local")
result = connection.execute(stmt)
for row in result:
	# "bob@local"
	print(row.email)
	# "bob@local"
	print(row._mapping["email"])
	# this does not work
	print(row["email"])
```

### ORM

reference the table class object and include `.scalars().all()` to get back instance objects
- use your `session` object, not the `connection` object
- `session.execute()` works here too if you want tuples instead
```
stmt = select(User).where(User.email.contains("bob"))
result = session.scalars(stmt).all()
for user in result:
	# "bob@local"
	print(user.email)
```


## `Session` (ORM only)

Core only uses a with-context and engine connect: `with engine.connect() as conn: ...`

`Session` handles flushing, identity mapping, and relationships
- `Session` **does not** auto-commit unless using `.begin()`
```
with Session(engine) as session:
	user = User(email="alice@local")
	session.add(user)
	session.commit()
```

`Session` with `begin()` to **use auto-committing**
```
with Session(engine) as session:
	with session.begin():
		user = User(email="alice@local")
		session.add(user)
		# no commit needed here
```


## Returning methods

| Method | Returns | Notes |
| -- | -- | -- |
| `.first()` | first row only |  |
| `.scalar()` | a single value, the **first column** of the **first row** | use with aggregations that return a **single value** |
| `.scalars()` | returns an iterable for the **first column**'s values | use with aggregations that return a **single column** |
| `.all()` | list of tuples that **contain individual row data** | native Python list and tuple types |
| `.one()` | one row | raises if 0 or more than 1 row returns |
| `.fetchall()` | same as `.all()` | interacts directly with the driver cursor; prefer `.all()` in most use cases |


## String matching, integer and datetime comparisons

| method | SQL equivalent | notes |
| -- | -- | -- |
| `.contains("bob")` | `LIKE '%bob%'`  | substring match anywhere |
| `.startswith("bob")` | `LIKE 'bob%'` | string starts with term |
| `.endswith("bob")` | `LIKE '%bob'` | string ends with term |
| `.like("%bob%")` | `LIKE '%bob%'` | manual wildcards |
| `.ilike("%bob%")` | `ILIKE '%bob%'` | case-insensitive manual wildcards |

```
.where(User.age > 21)
.where(User.age >= 18)
.where(User.age < 65)
.where(User.age.in_([20, 25, 30]))
# inclusive between
.where(User.age.between(30, 42))
```

```
start = datetime(2025, 1, 1, tzinfo=timezone.utc)
end = datetime(2025, 12, 31, tzinfo=timezone.utc)
cutoff_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
#
.where(User.latest_login < cutoff_date)
.where(User.created_at.between(start, end))
```
