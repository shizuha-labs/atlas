import json
import os
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
os.environ["ATLAS_JWT_SECRET"] = "test-secret"
os.environ["ATLAS_DB"] = "/tmp/atlas-service-test.db"
os.environ["ATLAS_CATALOG"] = str(Path(__file__).parent / "catalog.json")

Path("/tmp/atlas-service-test.db").unlink(missing_ok=True)
for suffix in ("-wal", "-shm"):
    Path(f"/tmp/atlas-service-test.db{suffix}").unlink(missing_ok=True)
Path(os.environ["ATLAS_CATALOG"]).write_text(
    json.dumps(
        {
            "title": "Shizuha System Atlas",
            "model_revision": "test-1",
            "nodes": [{"id": "shizuha"}],
        }
    ),
    encoding="utf-8",
)

from app import app  # noqa: E402
from store import connect, seed_system_map, upsert_design  # noqa: E402


def token(memberships, user_id=3):
    return jwt.encode(
        {"user_id": user_id, "username": "hritik", "organization_memberships": memberships},
        "test-secret",
        algorithm="HS256",
    )


@pytest.fixture()
def client(active_revocation_authority):
    with TestClient(app) as test:
        yield test


def test_member_sees_every_map_in_their_organizations(client):
    created = client.post(
        "/atlas/api/maps",
        headers={"Authorization": f"Bearer {token({'1': 'owner', '4': 'member'})}"},
        json={
            "organization_id": 4,
            "title": "Personal systems",
            "document": {"format": "shizuha-atlas", "version": 1, "model": {"title": "Personal systems"}},
        },
    )
    assert created.status_code == 201
    listed = client.get(
        "/atlas/api/maps",
        headers={"Authorization": f"Bearer {token({'1': 'owner', '4': 'member'})}"},
    )
    assert listed.status_code == 200
    found = {(item["organization_id"], item["id"], item["title"]) for item in listed.json()["maps"]}
    assert (1, "shizuha-system", "Shizuha System Atlas") in found
    assert (4, created.json()["id"], "Personal systems") in found
    assert listed.json()["total"] >= 2


def test_another_organization_cannot_read_these_maps(client):
    headers = {"Authorization": f"Bearer {token({'2': 'owner'}, user_id=9)}"}
    listing = client.get("/api/maps", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["maps"] == []
    assert listing.json()["total"] == 0
    denied = client.get("/atlas/api/maps/shizuha-system", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "You are not a member of this organization."


def test_system_map_is_not_rewritten_by_a_member(client):
    response = client.put(
        "/atlas/api/maps/shizuha-system",
        headers={"Authorization": f"Bearer {token({'1': 'owner'})}"},
        json={"title": "Replaced", "document": {"title": "Replaced"}},
    )
    assert response.status_code == 403


def test_catalog_revision_refreshes_the_seeded_map():
    path = Path(os.environ["ATLAS_CATALOG"])
    path.write_text(
        json.dumps({"title": "Shizuha System Atlas", "model_revision": "test-2", "nodes": []}),
        encoding="utf-8",
    )
    db = connect(os.environ["ATLAS_DB"])
    try:
        seed_system_map(db, path)
        row = db.execute(
            "SELECT document FROM maps WHERE id = ?", ("shizuha-system",)
        ).fetchone()
    finally:
        db.close()
    assert json.loads(row["document"])["model_revision"] == "test-2"


def test_unsigned_caller_is_rejected(client):
    assert client.get("/atlas/api/maps").status_code == 401


def test_library_refresh_keeps_the_search(client):
    response = client.get("/atlas", params={"q": "harbor", "org": "4"}, follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("/atlas/?") or location.startswith("http://testserver/atlas/?")
    assert "q=harbor" in location
    assert "org=4" in location


def test_imported_design_keeps_its_id_and_is_not_overwritten():
    db = connect(os.environ["ATLAS_DB"])
    try:
        first = upsert_design(
            db,
            "page-1",
            4,
            "Imported",
            {"format": "shizuha-atlas", "version": 1, "model": {"title": "Imported"}},
        )
        second = upsert_design(
            db,
            "page-1",
            4,
            "Changed outside Atlas",
            {"format": "shizuha-atlas", "version": 1, "model": {"title": "Changed"}},
        )
    finally:
        db.close()
    assert first["id"] == "page-1"
    assert second["title"] == "Imported"
    assert second["document"]["model"]["title"] == "Imported"


def test_library_searches_pages_and_stays_inside_memberships(client):
    headers = {"Authorization": f"Bearer {token({'1': 'owner', '4': 'member'})}"}
    created = []
    for title in ("Zebra harbor atlas", "Zebra harbor pumps"):
        response = client.post(
            "/atlas/api/maps",
            headers=headers,
            json={
                "organization_id": 4,
                "title": title,
                "document": {
                    "format": "shizuha-atlas",
                    "version": 1,
                    "model": {"title": title, "description": "Harbor note for the library"},
                },
            },
        )
        assert response.status_code == 201
        created.append(response.json()["id"])
    first = client.get(
        "/atlas/api/maps",
        headers=headers,
        params={"q": "ZEBRA HARBOR", "limit": 1, "offset": 0},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert len(body["maps"]) == 1
    assert "document" not in body["maps"][0]
    assert "Harbor note" in body["maps"][0]["summary"]
    second = client.get(
        "/atlas/api/maps",
        headers=headers,
        params={"q": "zebra harbor", "limit": 1, "offset": 1},
    ).json()
    assert {body["maps"][0]["id"], second["maps"][0]["id"]} == set(created)
    own_org = client.get(
        "/atlas/api/maps",
        headers=headers,
        params={"q": "zebra harbor", "organization_id": 4},
    ).json()
    assert own_org["total"] == 2
    other_org = client.get(
        "/atlas/api/maps",
        headers=headers,
        params={"q": "zebra harbor", "organization_id": 1},
    ).json()
    assert other_org["total"] == 0
    foreign = client.get("/atlas/api/maps", headers=headers, params={"organization_id": 2})
    assert foreign.status_code == 200
    foreign_body = foreign.json()
    assert foreign_body["maps"] == []
    assert foreign_body["total"] == 0
    assert foreign_body["limit"] == 24
    assert "system" in foreign_body["kinds"]
    designs = client.get(
        "/atlas/api/maps",
        headers=headers,
        params={"q": "zebra harbor", "kind": "design"},
    ).json()
    assert designs["total"] == 2
    systems = client.get("/atlas/api/maps", headers=headers, params={"kind": "system"}).json()
    assert systems["maps"]
    assert all(item["kind"] == "system" for item in systems["maps"])
    percent = client.post(
        "/atlas/api/maps",
        headers=headers,
        json={
            "organization_id": 4,
            "title": "100% ready",
            "document": {"format": "shizuha-atlas", "version": 1, "model": {"title": "100% ready"}},
        },
    )
    assert percent.status_code == 201
    wildcard = client.get("/atlas/api/maps", headers=headers, params={"q": "%"}).json()
    assert [item["id"] for item in wildcard["maps"]] == [percent.json()["id"]]
    capped = client.get("/atlas/api/maps", headers=headers, params={"limit": 500}).json()
    assert capped["limit"] == 60
    assert "document" not in capped["maps"][0]


def test_local_password_signs_in_without_identity(monkeypatch):
    monkeypatch.setenv("ATLAS_LOCAL_PASSWORD", "correct horse")
    monkeypatch.delenv("ATLAS_JWKS_URL", raising=False)
    monkeypatch.delenv("SHIZUHA_REVOCATION_STATUS_URL", raising=False)
    import token_revocation
    token_revocation._REVOCATION_CACHE.clear()
    with TestClient(app) as test:
        assert test.get("/atlas/api/auth").json()["mode"] == "local"
        denied = test.get("/atlas/api/maps")
        assert denied.status_code == 401
        assert denied.json()["detail"] == "Sign in to this Atlas."
        wrong = test.post("/atlas/api/login", json={"username": "ada", "password": "nope"})
        assert wrong.status_code == 401
        signed = test.post("/atlas/api/login", json={"username": "ada", "password": "correct horse"})
        assert signed.status_code == 200
        header = {"Authorization": f"Bearer {signed.json()['access_token']}"}
        listed = test.get("/atlas/api/maps", headers=header)
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1
        who = test.get("/atlas/api/session", headers=header)
        assert who.status_code == 200
        assert who.json()["username"] == "ada"
        assert who.json()["memberships"] == {"1": "owner"}


def test_platform_mode_rejects_local_password(monkeypatch, client):
    monkeypatch.setenv("ATLAS_JWKS_URL", "https://identity.example/jwks")
    monkeypatch.setenv("ATLAS_LOCAL_PASSWORD", "correct horse")
    assert client.get("/atlas/api/auth").json() == {"mode": "platform"}
    response = client.post("/atlas/api/login", json={"password": "correct horse"})
    assert response.status_code == 404
