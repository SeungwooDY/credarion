import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse

from app.auth_deps import enforce_org_scope
from app.routers import (
    auth,
    chat,
    erp,
    escalations,
    invoices,
    notifications,
    orgs,
    reconciliation,
    signoffs,
    statements,
    users,
)

# Configure logging so reconciliation debug output is visible
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("app.reconciliation").setLevel(logging.DEBUG)

app = FastAPI(title="Credarion API", version="0.1.0")

# Auth endpoints are public (login) or self-guarding (me). Every other data
# router requires a valid session and auto-scopes any org_id to the caller's
# account via enforce_org_scope.
_protected = [Depends(enforce_org_scope)]

app.include_router(auth.router)
app.include_router(chat.router, dependencies=_protected)
app.include_router(statements.router, dependencies=_protected)
app.include_router(erp.router, dependencies=_protected)
app.include_router(orgs.router, dependencies=_protected)
app.include_router(reconciliation.router, dependencies=_protected)
app.include_router(invoices.router, dependencies=_protected)
app.include_router(escalations.router, dependencies=_protected)
app.include_router(signoffs.router, dependencies=_protected)
app.include_router(notifications.router, dependencies=_protected)
app.include_router(users.router, dependencies=_protected)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def upload_ui() -> str:
    """Serve the upload test page."""
    html_path = Path(__file__).parent / "static" / "upload.html"
    return html_path.read_text(encoding="utf-8")
