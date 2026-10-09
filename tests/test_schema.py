"""The migrations build the schema the platform expects."""


def test_migrations_apply(database):
    with database.connect("admin") as conn:
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'psst'")}
    assert {"places", "items", "revisions", "claims", "evidence", "snapshots", "checks", "transitions"} <= tables
