import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.routers import chat, erp, invoices, orgs, periods, reconciliation, statements

# Configure logging so reconciliation debug output is visible
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("app.reconciliation").setLevel(logging.DEBUG)

app = FastAPI(title="Credarion API", version="0.1.0")

app.include_router(chat.router)
app.include_router(statements.router)
app.include_router(erp.router)
app.include_router(orgs.router)
app.include_router(periods.router)
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
