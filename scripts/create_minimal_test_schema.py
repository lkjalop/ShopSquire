from sqlalchemy import create_engine, MetaData, Table, Column, Text, Integer
import os

def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("No DATABASE_URL set; skipping minimal schema create")
        return
    print(f"Creating minimal test schema on {db_url}")
    engine = create_engine(db_url, future=True)
    meta = MetaData()

    Table(
        "security_events",
        meta,
        Column("id", Text, primary_key=True),
        Column("event_time", Text),
        Column("path", Text),
        Column("severity", Text),
        Column("verdict_score", Integer),
        Column("details", Text),
        Column("escalated", Integer, default=0),
        Column("blocked", Integer, default=0),
    )

    Table(
        "incidents",
        meta,
        Column("id", Text, primary_key=True),
        Column("event_id", Text),
        Column("created_at", Text),
        Column("created_by", Text),
        Column("severity", Text),
        Column("title", Text),
        Column("description", Text),
        Column("status", Text, default='open'),
    )

    meta.create_all(engine)
    print("Minimal schema created")

if __name__ == '__main__':
    main()
