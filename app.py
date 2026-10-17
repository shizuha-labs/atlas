"""Atlas HTTP service. Maps belong to an organization, not to Wiki."""

from __future__ import annotations

import hmac
import os
import re
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import jwt
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from auth import verify_token
from store import (
    connect,
    create_map,
    get_map,
    list_maps,
    map_kinds,
    refresh_empty_summaries,
    seed_system_map,
    update_map,
)

_KIND = re.compile(r"^[a-z0-9_-]{1,32}$")

ROOT = Path(__file__).resolve().parent
DB_PATH = os.environ.get("ATLAS_DB", "/tmp/atlas.db")
CATALOG = Path(os.environ.get("ATLAS_CATALOG", ROOT / "catalog" / "sample.json"))
STATIC = ROOT / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with database() as db:
        seed_system_map(db, CATALOG)
        refresh_empty_summaries(db)
    yield


app = FastAPI(title="Shizuha Atlas", lifespan=lifespan)


@contextmanager
def database():
    db = connect(DB_PATH)
    try:
        yield db
    finally:
        db.close()


def _sign_in_detail() -> str:
    if os.environ.get("ATLAS_JWKS_URL", "").strip():
        return "Sign in with Shizuha ID."
    if os.environ.get("ATLAS_JWT_SECRET", "").strip():
        return "Sign in to this Atlas."
    return "Sign in with Shizuha ID."


def caller_from(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail=_sign_in_detail())
    try:
        return verify_token(authorization.removeprefix("Bearer ").strip())
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=_sign_in_detail()) from exc


def require_org(caller, organization_id: int) -> None:
    if not caller.allows(organization_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this organization.",
        )


def explorer_model(document: dict) -> dict:
    nested = document.get("model") if isinstance(document, dict) else None
    if isinstance(nested, dict):
        return nested
    return document


class MapWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    document: dict = Field(default_factory=dict)
    organization_id: int | None = None


class LocalLogin(BaseModel):
    username: str = "atlas"
    password: str = ""


api = APIRouter()


@app.get("/health")
def health():
    return {"status": "ok", "service": "atlas"}


@api.get("/session")
def session(authorization: str | None = Header(default=None)):
    caller = caller_from(authorization)
    return {
        "user_id": caller.user_id,
        "username": caller.username,
        "is_staff": caller.is_staff,
        "memberships": caller.memberships,
    }


@api.get("/auth")
def auth_mode():
    if os.environ.get("ATLAS_JWKS_URL", "").strip():
        return {"mode": "platform"}
    if os.environ.get("ATLAS_JWT_SECRET", "").strip():
        name = os.environ.get("ATLAS_LOCAL_ORGANIZATION", "Local").strip() or "Local"
        return {
            "mode": "local",
            "organization_id": "1",
            "organization_name": name,
            "password": bool(os.environ.get("ATLAS_LOCAL_PASSWORD", "").strip()),
        }
    return {"mode": "unconfigured"}


@api.post("/login")
def local_login(body: LocalLogin):
    if os.environ.get("ATLAS_JWKS_URL", "").strip():
        raise HTTPException(status_code=404, detail="This Atlas uses Shizuha ID.")
    secret = os.environ.get("ATLAS_JWT_SECRET", "").strip()
    expected = os.environ.get("ATLAS_LOCAL_PASSWORD", "")
    if not secret or not expected:
        raise HTTPException(status_code=404, detail="Local sign-in is not configured.")
    if not hmac.compare_digest(body.password, expected):
        raise HTTPException(status_code=401, detail="Wrong password.")
    username = " ".join(body.username.split())[:80] or "atlas"
    encoded = jwt.encode(
        {
            "user_id": 1,
            "username": username,
            "organization_memberships": {"1": "owner"},
            "exp": int(time.time()) + 12 * 60 * 60,
        },
        secret,
        algorithm="HS256",
    )
    if isinstance(encoded, bytes):
        encoded = encoded.decode()
    return {"access_token": encoded, "token_type": "bearer"}


@api.get("/maps")
def maps(
    authorization: str | None = Header(default=None),
    q: str = "",
    organization_id: int | None = None,
    kind: str = "",
    limit: int = 24,
    offset: int = 0,
):
    caller = caller_from(authorization)
    query = " ".join(q.split())[:80]
    kind_text = kind.strip().lower()
    bounded = min(max(limit, 1), 60)
    start = min(max(offset, 0), 100_000)
    organizations = caller.organizations()
    with database() as db:
        if kind_text and _KIND.fullmatch(kind_text) is None:
            return {
                "maps": [],
                "total": 0,
                "limit": bounded,
                "offset": start,
                "kinds": map_kinds(db, organizations),
            }
        found, total, kinds = list_maps(
            db,
            organizations,
            query=query,
            organization_id=organization_id,
            kind=kind_text,
            limit=bounded,
            offset=start,
        )
    return {
        "maps": found,
        "total": total,
        "limit": bounded,
        "offset": start,
        "kinds": kinds,
    }


@api.post("/maps", status_code=201)
def add_map(body: MapWrite, authorization: str | None = Header(default=None)):
    caller = caller_from(authorization)
    if body.organization_id is None:
        raise HTTPException(status_code=400, detail="Choose an organization.")
    require_org(caller, body.organization_id)
    document = body.document or {"format": "shizuha-atlas", "version": 1, "model": {}}
    try:
        with database() as db:
            item = create_map(db, body.organization_id, body.title, document, caller.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item["model"] = explorer_model(item["document"])
    return item


@api.get("/maps/{map_id}")
def read_map(map_id: str, authorization: str | None = Header(default=None)):
    caller = caller_from(authorization)
    with database() as db:
        item = get_map(db, map_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No map with that id.")
    require_org(caller, item["organization_id"])
    item["model"] = explorer_model(item["document"])
    return item


@api.put("/maps/{map_id}")
def write_map(
    map_id: str,
    body: MapWrite,
    authorization: str | None = Header(default=None),
):
    caller = caller_from(authorization)
    with database() as db:
        current = get_map(db, map_id)
        if current is None:
            raise HTTPException(status_code=404, detail="No map with that id.")
        require_org(caller, current["organization_id"])
        try:
            item = update_map(db, map_id, body.title, body.document)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="No map with that id.")
    item["model"] = explorer_model(item["document"])
    return item


app.include_router(api, prefix="/api")
app.include_router(api, prefix="/atlas/api")


@app.get("/")
def root():
    return RedirectResponse("/atlas/", status_code=302)


def _static_file(relative: str) -> FileResponse | None:
    if not relative or ".." in relative.split("/"):
        return None
    candidate = (STATIC / relative).resolve()
    if not str(candidate).startswith(str(STATIC.resolve())) or not candidate.is_file():
        return None
    response = FileResponse(candidate)
    if relative == "index.html" or relative.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache"
    elif relative.startswith("assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.get("/atlas")
def atlas_slash(request: Request):
    # A filtered library lives at /atlas?q=… until refresh. Keep that query.
    target = "/atlas/"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(target, status_code=302)


@app.get("/atlas/")
def atlas_index():
    page = _static_file("index.html")
    if page is None:
        raise HTTPException(status_code=503, detail="Atlas is starting.")
    return page


@app.get("/atlas/{asset_path:path}")
def atlas_asset(asset_path: str):
    if asset_path in {"api", "favicon.ico"} or asset_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found.")
    found = _static_file(asset_path)
    if found is not None:
        return found
    page = _static_file("index.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return page
