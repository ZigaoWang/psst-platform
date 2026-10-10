"""The migrations build the schema the platform expects."""


def test_migrations_apply(database):
    with database.connect("admin") as conn:
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'psst'")}
    assert {"places", "items", "revisions", "claims", "evidence", "snapshots", "checks", "transitions"} <= tables


def test_the_backup_exports_every_table(database, tmp_path):
    from psst.core import backup, db
    with db.open_connection(database.url("admin")) as conn:
        counts = backup.export(conn, tmp_path)
    assert "places" in counts and (tmp_path / "places").is_dir()
