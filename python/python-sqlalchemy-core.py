#!/usr/bin/env python3


#
# this demonstrates SQLAlchemy 2.x Core-style usage
#
# references
# https://docs.sqlalchemy.org/
# https://stackoverflow.com/questions/34322471/sqlalchemy-engine-connection-and-session-difference
#
# uv add sqlalchemy psycopg2-binary polars
#


import uuid
from datetime import datetime, timezone
#
import polars as pl
# you could just do "import sqlalchemy as sa" then use sa.Integer, sa.String, etc
from sqlalchemy import Table, Column, ForeignKey, MetaData, Boolean, Integer, String, DateTime
from sqlalchemy import create_engine, select, insert, inspect, func, and_, or_, text, delete, distinct
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
# import aliases for different databases
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert


#===========================
# create the connection engine
#===========================

# create the "engine" that handles database connections, pooling, dialects, etc
# adding echo=True shows debug log and SQL output for ALL commands; remove in projects and production
#engine = create_engine("sqlite:///database.sqlite", echo=True)
#engine = create_engine("sqlite:///database.sqlite")
# postgresql
#engine = create_engine("postgresql://user:password@host/database")
engine = create_engine("postgresql://padmin:abcd1234@localhost:5432/dev_db")

# cleanup for demo - deletes any existing tables
with engine.begin() as conn:
	# CASCADE is useful if there are foreign keys or views depending on these tables
	conn.execute(text('DROP TABLE IF EXISTS "user_prefs" CASCADE;'))
	conn.execute(text('DROP TABLE IF EXISTS "user" CASCADE;'))


#===========================
# create metadata objects (schema definition)
#===========================

# "MetaData is a container object that keeps together many different features of a database (or multiple databases) being described."
metadata = MetaData()

# create user table
# UUID(as_uuid=True) returns a Python uuid.UUID object when fetched via SQLAlchemy
# other tools just see the UUID as a string
user_table = Table(
	"user",
	metadata,
	Column("user_id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
	#Column("user_id", Integer, primary_key=True, autoincrement=True),
	Column("email", String(200), nullable=False, unique=True),
	Column("enabled", Boolean(), default=False, nullable=False),
	# the database receives the proper UTC datetime, and can use NOW(), INTERVAL, etc in queries
	Column("created_at", DateTime(timezone=True)),
	Column("latest_login", DateTime(timezone=True)),
	# should add password_hash
)

# create user preferences table
user_prefs_table = Table(
	"user_prefs",
	metadata,
	#Column("pref_id", Integer, primary_key=True, autoincrement=True),
	Column("user_id", UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True),
	Column("username", String(100), nullable=False), #, unique=True),
	Column("first_name", String(100)),
	Column("last_name", String(100)),
	Column("title_prefix", String(100)),
	Column("nickname", String(100)),
)

# create a table to drop
drop_this_table = Table(
	"drop_me",
	metadata,
	Column("x_id", Integer, primary_key=True),
)

# create all objects via metadata
#   DOES auto commit
#   DOES NOT create the database, unless using a sqlite file
#   DOES NOT create tables that already exist
#   ** use alembic for migrations **
metadata.create_all(engine)
#
# for connecting to existing database and reading data
# "reflect" the database (get all tables and their schemas)
#metadata.reflect(bind=engine)


#===========================
# inspect tables, columns, keys
#===========================

# print table names
print("\n" + " table names via inspect() ".center(50, "="))
print(inspect(engine).get_table_names())

#print(repr(metadata.tables))
print("\n" + " all table names and attributes ".center(50, "="))
for table in metadata.sorted_tables:
	print(table.name)
	# use .c instead of .columns (both work)
	print(table.c.keys())
	for column in table.c:
		print(column.name, column.type, repr(column.type))
	print()

# view column keys
print("\n" + " specific table columns and keys ".center(50, "="))
print(user_table.columns.keys())
for column in user_table.columns:
	print(column.name, column.type, repr(column.type))


#===========================
# drop a table
# DOES AUTO COMMIT
#===========================

# drop a table - DOES AN AUTO COMMIT
drop_this_table.drop(engine, checkfirst=True)
# also remove the dropped table from metadata
metadata.remove(drop_this_table)
print("\n" + " tables remaining after drop() ".center(50, "="))
for table in metadata.sorted_tables:
	print(table.name)


#===========================
# insert data
#===========================

# dicts are easier than positional inserts (list of tuples) since values don't need to match the table's column order
# "enabled defaults to false in the schema
new_users = [
	{"username":"bob", "email":"bob@local", "first_name":"bob".title(), "last_name":"roberts".title()},
	{"username":"bobadmin", "email":"bobadmin@local", "first_name":"bob".title(), "last_name":"roberts".title(), "nickname":"BobTheBuilder"},
	{"username":"alice", "email":"alice@local", "first_name":"alice".title(), "last_name":"allison".title()},
	{"username":"aliceadmin", "email":"aliceadmin@local", "first_name":"alice".title(), "last_name":"allison".title(), "nickname":"AliceInWonderland"},
	{"username":"bob2", "email":"bob@local", "first_name":"bob".title(), "last_name":"roberts".title()},
	{"username":"alice2", "email":"alice@local", "first_name":"alice".title(), "last_name":"allison".title()},
]
# if manually assigning user_id values, pass the actual uuid.uuid4() object, which sqlalchemy is expecting
#for u in new_users:
#	# do not do this: u["user_id"] = str(uuid.uuid4())
#	u["user_id"] = uuid.uuid4()


#===========================
# bulk insert with .returning()
# this demonstrates letting the database issue user IDs, getting those back in the response,
#   then using those IDs to populate the preferences table
#
# "with" context DOES auto commit on successful exit
#===========================

# create SQL insert statements
# these are NOT "prepared statements" in a SQL sense
# these could also just be wrapped inside conn.execute(...) below

# new_users contains more values than the user table can handle
#   insert only the proper columns to the user table, receive autogenerated UUIDs, then use those for user_prefs
now = datetime.now(timezone.utc)
user_table_inserts = [{"email": u["email"], "created_at": now, "latest_login": now} for u in new_users]
# the database receives the proper UTC datetime, and can use NOW(), INTERVAL, etc in queries

# .returning() returns the specified values (autogenerated UUIDs and their emails)
statement = (
	pg_insert(user_table)
	.values(user_table_inserts)
	.on_conflict_do_nothing(index_elements=["email"])
	.returning(user_table.c.user_id, user_table.c.email)
)

with engine.begin() as conn:
	# bulk insert users (using pg_insert)
	# .returning() returns the specified values (autogenerated UUIDs and their emails)
	result = conn.execute(statement)

	# build a lookup dictionary using the email (key) and the generated user_id (value)
	# DEMO: removing the table deletes at the top of the script, will cause this to fail, if you re-run the script
	email_to_uuid = {row.email: row.user_id for row in result}
	print("\n" + " email_to_uuid lookup dictionary ".center(50, "="))
	print(email_to_uuid)
	
	# create a new list-of-dictionaries for user_prefs
	#   containing the correct foreign key (user_id), as captured by .returning() and
	#   stored in the "email_to_uuid" lookup dictionary
	user_prefs_table_inserts = [
		{
			"user_id": email_to_uuid[u["email"]],
			"username": u.get("username", None),
			"first_name": u.get("first_name", None),
			"last_name": u.get("last_name", None),
			"nickname": u.get("nickname", None)
		}
		for u in new_users
	]

	# bulk insert the user preferences, using the pg_insert import alias
	# the "upsert" via ON CONFLICT DO NOTHING, functionally does nothing here, due to
	#   dropping tables at the top of the script for demonstration and using the lookup
	#   dict populated from returning()
	if user_prefs_table_inserts:
		conn.execute(
			# this block could also be a statement saved as a variable
			pg_insert(user_prefs_table).values(user_prefs_table_inserts)
			.on_conflict_do_nothing(index_elements=["user_id"])
		)
		print("\n" + " inserted users and linked preferences ".center(50, "="))


#===========================
# view all contents using outer .join()
#===========================

print("\n" + " viewing tables using a big join ".center(50, "="))
with engine.connect() as conn:
	# outer join the results
	# this would be the raw SQL
	'''
	SELECT "user".email, "user".enabled, user_prefs.username, user_prefs.first_name, user_prefs.last_name 
	FROM "user" 
	LEFT OUTER JOIN user_prefs ON "user".user_id = user_prefs.user_id
	'''
	# explicitly list columns to pull back
	join_stmt = select(
		user_table.c.email,
		user_table.c.enabled,
		user_prefs_table.c.username,
		user_prefs_table.c.first_name,
		user_prefs_table.c.last_name
	# the FROM "user" (the object is user_table)
	).select_from(
		# user_table is the left, user_prefs_table is the right
		# user_id matchup is the ON condition
		# LEFT OUTER JOIN = include all left (user) values, even if there are no right (user_prefs) values
		user_table.join(user_prefs_table, user_table.c.user_id == user_prefs_table.c.user_id, isouter=True)
	)
	
	result = conn.execute(join_stmt)
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

		# select all
		rows = conn.execute(text(f'SELECT * FROM "{table_name}"')).fetchall()

		if not rows:
			print("--- this table is empty ---)")
		for row in rows:
			print(row)


#===========================
# delete user then view both tables again
#===========================

# use OR and AND statements, indented for readability
delete_statement = delete(user_table).where(
	or_(
		user_table.c.email == "bob@local",
		and_(
			or_(
				user_table.c.enabled == False,
				# also check None in case there is a NULL (None)
				user_table.c.enabled == None,
			),
			user_table.c.email.contains("bob"),
		)
	)
)
with engine.begin() as conn:
	result = conn.execute(delete_statement)


print("\n" + " dumping contents - after delete ".center(50, "="))
with engine.connect() as conn:
	for table_name in inspect(engine).get_table_names():
		print(f"\n--- table: {table_name} ---")
		rows = conn.execute(text(f'SELECT * FROM "{table_name}"')).fetchall()
		if not rows:
			print("--- this table is empty ---)")
		for row in rows:
			print(row)


#===========================
# use func methods and distinct
#===========================

with engine.connect() as conn:
	print("\n" + " select(func.count(user_table.c.user_id)) ".center(70, "="))
	stmt = select(func.count(user_table.c.user_id))
	# scalar returns a single value as a native datatype (here, int)
	result = conn.execute(stmt).scalar()
	print(f"\n--- total users in user_table ---")
	print(f"{result} ({type(result).__name__})")
	#
	print("\n" + " select(distinct(user_table.c.email)) ".center(70, "="))
	stmt = select(distinct(user_table.c.email))
	# if you import distinct, you can select(distinct(table.c.name))
	# scalars returns a SQLAlchemy iterable
	result = conn.execute(stmt).scalars()
	print(f"\n--- distinct emails in user_table ---")
	for r in result:
		print(f"{r} ({type(r).__name__})")
	#
	print("\n" + " select(func.count(distinct(user_table.c.email))) ".center(70, "="))
	stmt = select(func.count(distinct(user_table.c.email)))
	# scalar returns the first column of the first row (useful for a single statistic)
	result = conn.execute(stmt).scalar()
	print(f"\n--- count of distinct emails in user_table ---")
	print(f"{result} ({type(result).__name__})")


#===========================
# results to polars dataframe
#===========================

print("\n" + " query results to Polars dataframe ".center(50, "="))

# raw SQL
# DO NOT PLACE WILDCARDS (%) IN THE MAIN TEXT STRING
#   SQLAlchemy would escape them with more % signs, creating "%%alice%%"
# use single quotes, as you need double quotes around the table
query = text('SELECT * FROM "user" WHERE email LIKE :pattern').bindparams(pattern="%alice%")
df = pl.read_database(query=query, connection=engine)
print(f"\n--- DF from raw SQL ---")
with pl.Config(tbl_rows=-1, set_fmt_str_lengths=100):
	print(df)

# Core expressions
query = select(user_table).where(user_table.c.email.contains("alice"))
df = pl.read_database(query=query, connection=engine)
print(f"\n--- DF from methods ---")
with pl.Config(tbl_rows=-1, set_fmt_str_lengths=100):
	print(df)


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

======== email_to_uuid lookup dictionary =========
{'bob@local': UUID('75afdce6-316b-43ce-b56d-f6a921736cd8'), 'bobadmin@local': UUID('b63165dc-39ed-48c1-9e54-6820fd63ec81'), 'alice@local': UUID('56d97b05-b4ae-4fde-bcf2-1a21442547db'), 'aliceadmin@local': UUID('e7b06c34-5314-4723-98ac-563f744daec9')}

===== inserted users and linked preferences ======

======== viewing tables using a big join =========
('bob@local', False, 'bob', 'Bob', 'Roberts')
('bobadmin@local', False, 'bobadmin', 'Bob', 'Roberts')
('alice@local', False, 'alice', 'Alice', 'Allison')
('aliceadmin@local', False, 'aliceadmin', 'Alice', 'Allison')

========= dumping all tables in database =========

--- table: user_from_df ---
('5e252183-9c62-4726-87bd-a572fdf483e5', 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('0dbf17b1-948c-4db5-80d1-eac1e6af12d1', 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('fe82ec04-fe5f-457f-a140-0a840456be23', 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))

--- table: user ---
(UUID('75afdce6-316b-43ce-b56d-f6a921736cd8'), 'bob@local', False, datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc))
(UUID('b63165dc-39ed-48c1-9e54-6820fd63ec81'), 'bobadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc))
(UUID('56d97b05-b4ae-4fde-bcf2-1a21442547db'), 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc))
(UUID('e7b06c34-5314-4723-98ac-563f744daec9'), 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc))

--- table: user_prefs ---
(UUID('75afdce6-316b-43ce-b56d-f6a921736cd8'), 'bob', 'Bob', 'Roberts', None, None)
(UUID('b63165dc-39ed-48c1-9e54-6820fd63ec81'), 'bobadmin', 'Bob', 'Roberts', None, 'BobTheBuilder')
(UUID('56d97b05-b4ae-4fde-bcf2-1a21442547db'), 'alice', 'Alice', 'Allison', None, None)
(UUID('e7b06c34-5314-4723-98ac-563f744daec9'), 'aliceadmin', 'Alice', 'Allison', None, 'AliceInWonderland')

======== dumping contents - after delete =========

--- table: user_from_df ---
('5e252183-9c62-4726-87bd-a572fdf483e5', 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('0dbf17b1-948c-4db5-80d1-eac1e6af12d1', 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))
('fe82ec04-fe5f-457f-a140-0a840456be23', 'alice2@local', False, datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 5, 7, 85854, tzinfo=datetime.timezone.utc))

--- table: user ---
(UUID('56d97b05-b4ae-4fde-bcf2-1a21442547db'), 'alice@local', False, datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc))
(UUID('e7b06c34-5314-4723-98ac-563f744daec9'), 'aliceadmin@local', False, datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 31, 13, 14, 39, 573631, tzinfo=datetime.timezone.utc))

--- table: user_prefs ---
(UUID('56d97b05-b4ae-4fde-bcf2-1a21442547db'), 'alice', 'Alice', 'Allison', None, None)
(UUID('e7b06c34-5314-4723-98ac-563f744daec9'), 'aliceadmin', 'Alice', 'Allison', None, 'AliceInWonderland')

============== select(func.count(user_table.c.user_id)) ==============

--- total users in user_table ---
2 (int)

================ select(distinct(user_table.c.email)) ================

--- distinct emails in user_table ---
alice@local (str)
aliceadmin@local (str)

========== select(func.count(distinct(user_table.c.email))) ==========

--- count of distinct emails in user_table ---
2 (int)

======= query results to Polars dataframe ========

--- DF from raw SQL ---
shape: (2, 5)
┌───────────────────────┬──────────────────┬─────────┬──────────────────────┬──────────────────────┐
│ user_id               ┆ email            ┆ enabled ┆ created_at           ┆ latest_login         │
│ ---                   ┆ ---              ┆ ---     ┆ ---                  ┆ ---                  │
│ object                ┆ str              ┆ bool    ┆ datetime[μs, UTC]    ┆ datetime[μs, UTC]    │
╞═══════════════════════╪══════════════════╪═════════╪══════════════════════╪══════════════════════╡
│ 56d97b05-b4ae-4fde-bc ┆ alice@local      ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ f2-1a21442547db       ┆                  ┆         ┆ 13:14:39.573631 UTC  ┆ 13:14:39.573631 UTC  │
│ e7b06c34-5314-4723-98 ┆ aliceadmin@local ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ ac-563f744daec9       ┆                  ┆         ┆ 13:14:39.573631 UTC  ┆ 13:14:39.573631 UTC  │
└───────────────────────┴──────────────────┴─────────┴──────────────────────┴──────────────────────┘

--- DF from methods ---
shape: (2, 5)
┌───────────────────────┬──────────────────┬─────────┬──────────────────────┬──────────────────────┐
│ user_id               ┆ email            ┆ enabled ┆ created_at           ┆ latest_login         │
│ ---                   ┆ ---              ┆ ---     ┆ ---                  ┆ ---                  │
│ object                ┆ str              ┆ bool    ┆ datetime[μs, UTC]    ┆ datetime[μs, UTC]    │
╞═══════════════════════╪══════════════════╪═════════╪══════════════════════╪══════════════════════╡
│ 56d97b05-b4ae-4fde-bc ┆ alice@local      ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ f2-1a21442547db       ┆                  ┆         ┆ 13:14:39.573631 UTC  ┆ 13:14:39.573631 UTC  │
│ e7b06c34-5314-4723-98 ┆ aliceadmin@local ┆ false   ┆ 2026-10-31           ┆ 2026-10-31           │
│ ac-563f744daec9       ┆                  ┆         ┆ 13:14:39.573631 UTC  ┆ 13:14:39.573631 UTC  │
└───────────────────────┴──────────────────┴─────────┴──────────────────────┴──────────────────────┘
'''
