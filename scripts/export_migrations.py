"""Export all Supabase migrations from the database to supabase/migrations/*.sql.

Run by the 'Export DB migrations' GitHub Action. Requires SUPABASE_DB_URL
(Supabase -> Settings -> Database -> Connection string / Session pooler URI).
"""
import os
import psycopg2

url = os.environ["SUPABASE_DB_URL"]
conn = psycopg2.connect(url)
cur = conn.cursor()
cur.execute(
    "select version, name, array_to_string(statements, E'\n') "
    "from supabase_migrations.schema_migrations order by version"
)
os.makedirs("supabase/migrations", exist_ok=True)
count = 0
for version, name, sql in cur.fetchall():
    fn = f"supabase/migrations/{version}_{name}.sql"
    with open(fn, "w", encoding="utf-8") as f:
        f.write((sql or "").rstrip() + "\n")
    print("wrote", fn)
    count += 1
print(f"exported {count} migrations")
