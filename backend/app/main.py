from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.routers import erp, invoices, orgs, reconciliation, statements

app = FastAPI(title="Credarion API", version="0.1.0")

app.include_router(statements.router)
app.include_router(erp.router)
app.include_router(orgs.router)
app.include_router(reconciliation.router)
app.include_router(invoices.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def upload_ui() -> str:
    """Serve the upload test page."""
    html_path = Path(__file__).parent / "static" / "upload.html"
    return html_path.read_text(encoding="utf-8")
