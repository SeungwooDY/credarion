from fastapi import FastAPI

from app.routers import statements

app = FastAPI(title="Credarion API", version="0.1.0")

app.include_router(statements.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
