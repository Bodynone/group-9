"""Back up file databases before first additive v2 migration."""

from pathlib import Path
import sqlite3
from uuid import uuid4


def backup_before_v2(store):
    if store.path == ":memory:":
        return None
    with store._lock:
        if store._connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_contexts'").fetchone():
            return None
        path = Path(store.path)
        destination = path.parent / "migration-backups" / (path.stem + "-pre-v2-" + str(uuid4()) + ".sqlite3")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as target:
            store._connection.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("迁移备份校验失败")
        return str(destination)
