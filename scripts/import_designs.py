"""Copy design maps into Atlas once. An id that already exists is left alone."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import connect, upsert_design  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: import_designs.py designs.json")
    rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("designs.json must be a list")
    db = connect(os.environ.get("ATLAS_DB", "/data/atlas.db"))
    inserted = 0
    try:
        for row in rows:
            before = db.execute("SELECT 1 FROM maps WHERE id = ?", (row["id"],)).fetchone()
            upsert_design(
                db,
                str(row["id"]),
                int(row["organization_id"]),
                str(row["title"]),
                row["document"],
            )
            if before is None:
                inserted += 1
    finally:
        db.close()
    print(json.dumps({"seen": len(rows), "inserted": inserted}))


if __name__ == "__main__":
    main()
