# Credarion Backend

FastAPI + PostgreSQL + SQLAlchemy 2.0 + Alembic.

## Setup

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # edit DATABASE_URL
```

## Database

```bash
# Apply migrations
alembic upgrade head

# Create a new migration (autogenerate from models)
alembic revision --autogenerate -m "description"
```

## Run

```bash
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health`

## Layout

```
backend/
  app/
    main.py       # FastAPI entrypoint
    config.py     # Pydantic settings
    db.py         # SQLAlchemy engine + Base
    models.py     # ORM models
  db/
    migrations/   # Alembic migrations
  alembic.ini
  pyproject.toml
```
