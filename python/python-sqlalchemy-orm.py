#!/usr/bin/env python3


#
# this demonstrates SQLAlchemy 2.x ORM-style usage
#
# references
# https://docs.sqlalchemy.org/
#
# uv add sqlalchemy psycopg2-binary polars pyarrow
#


import uuid
from datetime import datetime, timezone
#
import polars as pl
# ORM imports
from sqlalchemy import create_engine, select, inspect, func, and_, or_, text, delete, distinct
from sqlalchemy import Boolean, Integer, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
# for the dataframe-to-table section
from sqlalchemy import Table, MetaData, select


#===========================
# create the connection engine
#===========================

# create the "engine" that handles database connections, pooling, dialects, etc
engine = create_engine("postgresql://padmin:abcd1234@localhost:5432/dev_db")

# cleanup for demo - deletes any existing tables
with engine.begin() as conn:
	# CASCADE is useful if there are foreign keys or views depending on these tables
	conn.execute(text('DROP TABLE IF EXISTS "user_prefs" CASCADE;'))
	conn.execute(text('DROP TABLE IF EXISTS "user" CASCADE;'))


#===========================
# create declarative base and ORM models (schema definition)
#===========================

class Base(DeclarativeBase):
	pass


# create user model (this defines the user table)
class User(Base):
	__tablename__ = "user"
	user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
	email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
	enabled: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
	created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	latest_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	# SQLAlchemy magic - this attribute is the ORM relationship to the user preferences model
	user_prefs: Mapped["UserPrefs"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)

# create user preferences model (this defines the user_prefs table)
class UserPrefs(Base):
	__tablename__ = "user_prefs"
	user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True)
	username: Mapped[str] = mapped_column(String(100), nullable=False)
	first_name: Mapped[str | None] = mapped_column(String(100))
	last_name: Mapped[str | None] = mapped_column(String(100))
	title_prefix: Mapped[str | None] = mapped_column(String(100))
	nickname: Mapped[str | None] = mapped_column(String(100))
	# this attribute is the ORM relationship to the user model
	user: Mapped["User"] = relationship(back_populates="user_prefs")

# create a table to drop
class DropThisTable(Base):
	__tablename__ = "drop_me"
	x_id: Mapped[int] = mapped_column(Integer, primary_key=True)

# create all objects via Base metadata
Base.metadata.create_all(engine)


#===========================
# inspect tables, columns, keys
#===========================

# print table names
print("\n" + " table names via inspect() ".center(50, "="))
print(inspect(engine).get_table_names())

print("\n" + " all table names and attributes ".center(50, "="))
for table in Base.metadata.sorted_tables:
	print(table.name)
	print(table.c.keys())
	for column in table.c:
		print(column.name, column.type, repr(column.type))
	print()

# view column keys using model table attribute
print("\n" + " specific table columns and keys ".center(50, "="))
print(User.__table__.columns.keys())
for column in User.__table__.columns:
	print(column.name, column.type, repr(column.type))


#===========================
# drop a table
# DOES AUTO COMMIT
#===========================

DropThisTable.__table__.drop(engine, checkfirst=True)
# remove the dropped table from Base metadata
Base.metadata.remove(DropThisTable.__table__)
print("\n" + " tables remaining after drop() ".center(50, "="))
for table in Base.metadata.sorted_tables:
	print(table.name)


#===========================
# insert data (using ORM Session and model instances)
#===========================

new_users = [
	{"username": "bob", "email": "bob@local", "first_name": "bob".title(), "last_name": "roberts".title()},
	{"username": "bobadmin", "email": "bobadmin@local", "first_name": "bob".title(), "last_name": "roberts".title(), "nickname": "BobTheBuilder"},
	{"username": "alice", "email": "alice@local", "first_name": "alice".title(), "last_name": "allison".title()},
	{"username": "aliceadmin", "email": "aliceadmin@local", "first_name": "alice".title(), "last_name": "allison".title(), "nickname": "AliceInWonderland"},
	{"username": "bob2", "email": "bob2@local", "first_name": "bob".title(), "last_name": "roberts".title()},
	{"username": "alice2", "email": "alice2@local", "first_name": "alice".title(), "last_name": "allison".title()},
]

now = datetime.now(timezone.utc)

# the UUID is generated on the client side via uuid.uuid4 so  
#   we already know the ID and don't need .returning()
with Session(engine) as session:
	for u in new_users:
		# Create the User object and nest the UserPrefs object directly inside it
		user_obj = User(
			email=u["email"],
			created_at=now,
			latest_login=now,
			user_prefs=UserPrefs(
				username=u.get("username"),
				first_name=u.get("first_name"),
				last_name=u.get("last_name"),
				nickname=u.get("nickname")
			)
		)
		session.add(user_obj)
	
	session.commit()
	print("\n" + " inserted users and linked preferences via ORM ".center(50, "="))


#===========================
# view all contents using outer .join()
#===========================

print("\n" + " viewing tables using a big join ".center(50, "="))
with Session(engine) as session:
	# outer join the results
	# this would be the raw SQL
	'''
	SELECT "user".email, "user".enabled, user_prefs.username, user_prefs.first_name, user_prefs.last_name
	FROM "user"
	LEFT JOIN user_prefs ON "user".user_id = user_prefs.user_id;
	'''
	# explicitly list columns to pull back using Core-style join
	join_stmt = select(
		User.email,
		User.enabled,
		UserPrefs.username,
		UserPrefs.first_name,
		UserPrefs.last_name
	).select_from(
		# user_table is the left, user_prefs_table is the right
		# user_id matchup is the ON condition
		# LEFT OUTER JOIN = include all left (user) values, even if there are no right (user_prefs) values
		User.__table__.join(UserPrefs.__table__, User.user_id == UserPrefs.user_id, isouter=True)
	)
	
	result = session.execute(join_stmt)
	for row in result:
		print(row)


#===========================
# view all contents by looping over all tables and using SELECT *
#===========================

print("\n" + " dumping all tables in database ".center(50, "="))
with engine.connect() as conn:
	# loop through every table name found in the schema
	for table_name in inspect(engine).get_table_names():
		print(f"\n--- table: {table_name} ---")
		rows = conn.execute(text(f'SELECT * FROM "{table_name}"')).fetchall()
		if not rows:
			print("--- this table is empty ---")
		for row in rows:
			print(row)


#===========================
# delete user then view both tables again
#===========================

# use OR and AND statements on ORM attributes
delete_statement = delete(User).where(
	or_(
		User.email == "bob@local",
		and_(
			or_(
				User.enabled == False,
				User.enabled == None,
			),
			User.email.contains("bob"),
		)
	)
)

with Session(engine) as session:
	session.execute(delete_statement)
	session.commit()

print("\n" + " dumping contents - after delete ".center(50, "="))
with engine.connect() as conn:
	for table_name in inspect(engine).get_table_names():
		print(f"\n--- table: {table_name} ---")
		rows = conn.execute(text(f'SELECT * FROM "{table_name}"')).fetchall()
		if not rows:
			print("--- this table is empty ---")
		for row in rows:
			print(row)


#===========================
# use func methods and distinct
#===========================

with Session(engine) as session:
	print("\n" + " select(func.count(User.user_id)) ".center(70, "="))
	stmt = select(func.count(User.user_id))
	result = session.execute(stmt).scalar()
	print(f"\n--- total users in user table ---")
	print(f"{result} ({type(result).__name__})")
	#
	print("\n" + " select(distinct(User.email)) ".center(70, "="))
	stmt = select(distinct(User.email))
	result = session.execute(stmt).scalars()
	print(f"\n--- distinct emails in user table ---")
	for r in result:
		print(f"{r} ({type(r).__name__})")
	#
	print("\n" + " select(func.count(distinct(User.email))) ".center(70, "="))
	stmt = select(func.count(distinct(User.email)))
	result = session.execute(stmt).scalar()
	print(f"\n--- count of distinct emails in user table ---")
	print(f"{result} ({type(result).__name__})")


#===========================
# results to polars dataframe
#===========================

print("\n" + " query results to Polars dataframe ".center(50, "="))

# raw SQL
query = text('SELECT * FROM "user" WHERE email LIKE :pattern').bindparams(pattern="%alice%")
df = pl.read_database(query=query, connection=engine)
print(f"\n--- DF from raw SQL ---")
with pl.Config(tbl_rows=-1, set_fmt_str_lengths=100):
	print(df)

# ORM expressions
query = select(User).where(User.email.contains("alice"))
df = pl.read_database(query=query, connection=engine)
print(f"\n--- DF from ORM query ---")
with pl.Config(tbl_rows=-1, set_fmt_str_lengths=100):
	print(df)


#===========================
# make new table from polars dataframe and display it
# requires pyarrow
#===========================

print("\n" + " create table from Polars dataframe ".center(50, "="))
# Base.metadata won't automatically include this table until we reflect it
# can replace, fail, append
df.write_database(table_name="user_from_df", connection=engine, if_table_exists="replace")
# polars made the changes directly in postgres, so read the updated schema
metadata = MetaData()
user_from_df = Table("user_from_df", metadata, autoload_with=engine)

with Session(engine) as session:
	# equivalent to SELECT * FROM user_from_df
	stmt = select(user_from_df)
	rows = session.execute(stmt).fetchall()
	print(f"\n--- user_from_df rows ---")
	for row in rows:
		print(row)


# expected script output
'''
=========== table names via inspect() ============
['user_from_df', 'drop_me', 'user', 'user_prefs']

========= all table names and attributes =========
drop_me
['x_id']
x_id INTEGER Integer()

user
['user_id', 'email', 'enabled', 'created_at', 'latest_login']
user_id UUID UUID()
email VARCHAR(200) String(length=200)
enabled BOOLEAN Boolean()
created_at DATETIME DateTime(timezone=True)
latest_login DATETIME DateTime(timezone=True)

user_prefs
['user_id', 'username', 'first_name', 'last_name', 'title_prefix', 'nickname']
user_id UUID UUID()
username VARCHAR(100) String(length=100)
first_name VARCHAR(100) String(length=100)
last_name VARCHAR(100) String(length=100)
title_prefix VARCHAR(100) String(length=100)
nickname VARCHAR(100) String(length=100)


======== specific table columns and keys =========
['user_id', 'email', 'enabled', 'created_at', 'latest_login']
user_id UUID UUID()
email VARCHAR(200) String(length=200)
enabled BOOLEAN Boolean()
created_at DATETIME DateTime(timezone=True)
latest_login DATETIME DateTime(timezone=True)

========= tables remaining after drop() ==========
user
user_prefs

= inserted users and linked preferences via ORM ==

======== viewing tables using a big join =========
('bob@local', False, 'bob', 'Bob', 'Roberts')
('bobadmin@local', False, 'bobadmin', 'Bob', 'Roberts')
('alice@local', False, 'alice', 'Alice', 'Allison')
('aliceadmin@local', False, 'aliceadmin', 'Alice', 'Allison')
('bob2@local', False, 'bob2', 'Bob', 'Roberts')
('alice2@local', False, 'alice2', 'Alice', 'Allison')

========= dumping all tables in database =========

--- table: user_from_df ---
('5e252183-9c62-4726-87bd-a572fdf483e5', 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('0dbf17b1-948c-4db5-80d1-eac1e6af12d1', 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('fe82ec04-fe5f-457f-a140-0a840456be23', 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))

--- table: user ---
(UUID('37dfaf9f-5f54-4d1a-8131-51121ccc4fe7'), 'bob@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('15fc45e5-a99e-41d7-a6cf-48bdfc6a5c8a'), 'bobadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('8d459ff1-3d49-4519-8238-4f71a5d1dc20'), 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('95fdd163-473d-4333-8dbe-ce471e602d1d'), 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('597a3055-4eaf-49d7-b24a-8f5849e12c5f'), 'bob2@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('7bad728c-8120-4b6b-8a5d-3cec9efa294a'), 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))

--- table: user_prefs ---
(UUID('37dfaf9f-5f54-4d1a-8131-51121ccc4fe7'), 'bob', 'Bob', 'Roberts', None, None)
(UUID('15fc45e5-a99e-41d7-a6cf-48bdfc6a5c8a'), 'bobadmin', 'Bob', 'Roberts', None, 'BobTheBuilder')
(UUID('8d459ff1-3d49-4519-8238-4f71a5d1dc20'), 'alice', 'Alice', 'Allison', None, None)
(UUID('95fdd163-473d-4333-8dbe-ce471e602d1d'), 'aliceadmin', 'Alice', 'Allison', None, 'AliceInWonderland')
(UUID('597a3055-4eaf-49d7-b24a-8f5849e12c5f'), 'bob2', 'Bob', 'Roberts', None, None)
(UUID('7bad728c-8120-4b6b-8a5d-3cec9efa294a'), 'alice2', 'Alice', 'Allison', None, None)

======== dumping contents - after delete =========

--- table: user_from_df ---
('5e252183-9c62-4726-87bd-a572fdf483e5', 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('0dbf17b1-948c-4db5-80d1-eac1e6af12d1', 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('fe82ec04-fe5f-457f-a140-0a840456be23', 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))

--- table: user ---
(UUID('8d459ff1-3d49-4519-8238-4f71a5d1dc20'), 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('95fdd163-473d-4333-8dbe-ce471e602d1d'), 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
(UUID('7bad728c-8120-4b6b-8a5d-3cec9efa294a'), 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))

--- table: user_prefs ---
(UUID('8d459ff1-3d49-4519-8238-4f71a5d1dc20'), 'alice', 'Alice', 'Allison', None, None)
(UUID('95fdd163-473d-4333-8dbe-ce471e602d1d'), 'aliceadmin', 'Alice', 'Allison', None, 'AliceInWonderland')
(UUID('7bad728c-8120-4b6b-8a5d-3cec9efa294a'), 'alice2', 'Alice', 'Allison', None, None)

================== select(func.count(User.user_id)) ==================

--- total users in user table ---
3 (int)

==================== select(distinct(User.email)) ====================

--- distinct emails in user table ---
alice2@local (str)
alice@local (str)
aliceadmin@local (str)

============== select(func.count(distinct(User.email))) ==============

--- count of distinct emails in user table ---
3 (int)

======= query results to Polars dataframe ========

--- DF from raw SQL ---
shape: (3, 5)
┌───────────────────────┬──────────────────┬─────────┬──────────────────────┬──────────────────────┐
│ user_id               ┆ email            ┆ enabled ┆ created_at           ┆ latest_login         │
│ ---                   ┆ ---              ┆ ---     ┆ ---                  ┆ ---                  │
│ object                ┆ str              ┆ bool    ┆ datetime[μs, UTC]    ┆ datetime[μs, UTC]    │
╞═══════════════════════╪══════════════════╪═════════╪══════════════════════╪══════════════════════╡
│ 8d459ff1-3d49-4519-82 ┆ alice@local      ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ 38-4f71a5d1dc20       ┆                  ┆         ┆ 13:14:46.011578 UTC  ┆ 13:14:46.011578 UTC  │
│ 95fdd163-473d-4333-8d ┆ aliceadmin@local ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ be-ce471e602d1d       ┆                  ┆         ┆ 13:14:46.011578 UTC  ┆ 13:14:46.011578 UTC  │
│ 7bad728c-8120-4b6b-8a ┆ alice2@local     ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ 5d-3cec9efa294a       ┆                  ┆         ┆ 13:14:46.011578 UTC  ┆ 13:14:46.011578 UTC  │
└───────────────────────┴──────────────────┴─────────┴──────────────────────┴──────────────────────┘

--- DF from ORM query ---
shape: (3, 5)
┌───────────────────────┬──────────────────┬─────────┬──────────────────────┬──────────────────────┐
│ user_id               ┆ email            ┆ enabled ┆ created_at           ┆ latest_login         │
│ ---                   ┆ ---              ┆ ---     ┆ ---                  ┆ ---                  │
│ object                ┆ str              ┆ bool    ┆ datetime[μs, UTC]    ┆ datetime[μs, UTC]    │
╞═══════════════════════╪══════════════════╪═════════╪══════════════════════╪══════════════════════╡
│ 8d459ff1-3d49-4519-82 ┆ alice@local      ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ 38-4f71a5d1dc20       ┆                  ┆         ┆ 13:14:46.011578 UTC  ┆ 13:14:46.011578 UTC  │
│ 95fdd163-473d-4333-8d ┆ aliceadmin@local ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ be-ce471e602d1d       ┆                  ┆         ┆ 13:14:46.011578 UTC  ┆ 13:14:46.011578 UTC  │
│ 7bad728c-8120-4b6b-8a ┆ alice2@local     ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ 5d-3cec9efa294a       ┆                  ┆         ┆ 13:14:46.011578 UTC  ┆ 13:14:46.011578 UTC  │
└───────────────────────┴──────────────────┴─────────┴──────────────────────┴──────────────────────┘

======= create table from Polars dataframe =======

--- user_from_df rows ---
('8d459ff1-3d49-4519-8238-4f71a5d1dc20', 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
('95fdd163-473d-4333-8dbe-ce471e602d1d', 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
('7bad728c-8120-4b6b-8a5d-3cec9efa294a', 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 46, 11578, tzinfo=datetime.timezone.utc))
'''
