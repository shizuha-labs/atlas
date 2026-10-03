"""Organization maps. The system catalog ships inside this image."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SYSTEM_MAP_ID = "shizuha-system"
SYSTEM_ORG_ID = 1
MAX_DOCUMENT_BYTES = 2_000_000


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS maps (
            id TEXT PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            document TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(maps)")}
    # Summary sits beside the document so a library of thousands can search
    # without parsing every document on the list path.
    if "summary" not in columns:
        db.execute("ALTER TABLE maps ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
    db.execute(
        "CREATE INDEX IF NOT EXISTS maps_org ON maps(organization_id, updated_at)"
    )
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(document: dict) -> str:
    encoded = json.dumps(document, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("document is too large")
    return encoded


def document_summary(document: dict) -> str:
    if not isinstance(document, dict):
        return ""
    model = document.get("model")
    candidates = [document.get("description")]
    if isinstance(model, dict):
        candidates.append(model.get("description"))
    text = ""
    for value in candidates:
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            break
    if len(text) > 180:
        return text[:177].rstrip() + "…"
    return text


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def seed_system_map(db: sqlite3.Connection, catalog_path: Path) -> None:
    if not catalog_path.is_file():
        return
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload = _dump(document)
    title = document.get("title") or "Shizuha System Atlas"
    summary = document_summary(document)
    existing = db.execute(
        "SELECT document FROM maps WHERE id = ?", (SYSTEM_MAP_ID,)
    ).fetchone()
    if existing:
        current = json.loads(existing["document"])
        if current.get("model_revision") == document.get("model_revision"):
            return
        db.execute(
            """
            UPDATE maps
            SET title = ?, document = ?, summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (title, payload, summary, _now(), SYSTEM_MAP_ID),
        )
    else:
        db.execute(
            """
            INSERT INTO maps
                (id, organization_id, title, kind, document, summary, created_by, updated_at)
            VALUES (?, ?, ?, 'system', ?, ?, 0, ?)
            """,
            (SYSTEM_MAP_ID, SYSTEM_ORG_ID, title, payload, summary, _now()),
        )
    db.commit()


def _summary(row: sqlite3.Row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "organization_id": row["organization_id"],
        "title": row["title"],
        "kind": row["kind"],
        "updated_at": row["updated_at"],
        "summary": row["summary"] if "summary" in keys else "",
        "href": f"/atlas/maps/{row['id']}",
    }


def map_kinds(db: sqlite3.Connection, organization_ids: list[int]) -> list[str]:
    if not organization_ids:
        return []
    marks = ",".join("?" for _ in organization_ids)
    rows = db.execute(
        f"""
        SELECT DISTINCT kind FROM maps
        WHERE organization_id IN ({marks}) AND kind != ''
        ORDER BY kind
        """,
        organization_ids,
    ).fetchall()
    return [row["kind"] for row in rows]


def list_maps(
    db: sqlite3.Connection,
    organization_ids: list[int],
    query: str = "",
    organization_id: int | None = None,
    kind: str = "",
    limit: int = 24,
    offset: int = 0,
) -> tuple[list[dict], int, list[str]]:
    """One page of maps the caller can open. The page never includes documents."""
    kinds = map_kinds(db, organization_ids)
    if not organization_ids:
        return [], 0, kinds
    limit = max(1, min(int(limit), 60))
    offset = max(0, int(offset))
    selected = organization_ids
    if organization_id is not None:
        if organization_id not in organization_ids:
            return [], 0, kinds
        selected = [organization_id]
    marks = ",".join("?" for _ in selected)
    clauses = [f"organization_id IN ({marks})"]
    params: list = list(selected)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if query:
        like = _like(query)
        clauses.append("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')")
        params.extend([like, like])
    where = " AND ".join(clauses)
    total = db.execute(f"SELECT COUNT(*) AS n FROM maps WHERE {where}", params).fetchone()["n"]
    rows = db.execute(
        f"""
        SELECT id, organization_id, title, kind, updated_at, summary
        FROM maps
        WHERE {where}
        ORDER BY updated_at DESC, title COLLATE NOCASE
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return [_summary(row) for row in rows], int(total), kinds


def refresh_empty_summaries(db: sqlite3.Connection, limit: int = 40) -> None:
    rows = db.execute(
        "SELECT id, document FROM maps WHERE summary = '' LIMIT ?",
        (limit,),
    ).fetchall()
    changed = False
    for row in rows:
        try:
            document = json.loads(row["document"])
        except json.JSONDecodeError:
            continue
        text = document_summary(document)
        if not text:
            continue
        db.execute(
            "UPDATE maps SET summary = ? WHERE id = ? AND summary = ''",
            (text, row["id"]),
        )
        changed = True
    if changed:
        db.commit()


def get_map(db: sqlite3.Connection, map_id: str) -> dict | None:
    row = db.execute("SELECT * FROM maps WHERE id = ?", (map_id,)).fetchone()
    if row is None:
        return None
    item = _summary(row)
    item["document"] = json.loads(row["document"])
    item["created_by"] = row["created_by"]
    return item


def create_map(
    db: sqlite3.Connection,
    organization_id: int,
    title: str,
    document: dict,
    created_by: int,
) -> dict:
    map_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO maps
            (id, organization_id, title, kind, document, summary, created_by, updated_at)
        VALUES (?, ?, ?, 'design', ?, ?, ?, ?)
        """,
        (map_id, organization_id, title, _dump(document), document_summary(document), created_by, _now()),
    )
    db.commit()
    created = get_map(db, map_id)
    if created is None:
        raise RuntimeError("map disappeared after insert")
    return created


def upsert_design(
    db: sqlite3.Connection,
    map_id: str,
    organization_id: int,
    title: str,
    document: dict,
    created_by: int = 0,
) -> dict:
    """Insert a design copied from outside Atlas. A later edit in Atlas wins."""
    if not map_id or map_id == SYSTEM_MAP_ID:
        raise ValueError("a design needs its own id")
    if not isinstance(document, dict):
        raise ValueError("document must be an object")
    existing = get_map(db, map_id)
    if existing is not None:
        return existing
    db.execute(
        """
        INSERT INTO maps
            (id, organization_id, title, kind, document, summary, created_by, updated_at)
        VALUES (?, ?, ?, 'design', ?, ?, ?, ?)
        """,
        (map_id, organization_id, title, _dump(document), document_summary(document), created_by, _now()),
    )
    db.commit()
    created = get_map(db, map_id)
    if created is None:
        raise RuntimeError("map disappeared after insert")
    return created


def update_map(
    db: sqlite3.Connection,
    map_id: str,
    title: str,
    document: dict,
) -> dict | None:
    current = get_map(db, map_id)
    if current is None:
        return None
    if current["kind"] == "system":
        raise PermissionError("the system map is published with the Atlas image")
    db.execute(
        "UPDATE maps SET title = ?, document = ?, summary = ?, updated_at = ? WHERE id = ?",
        (title, _dump(document), document_summary(document), _now(), map_id),
    )
    db.commit()
    return get_map(db, map_id)
