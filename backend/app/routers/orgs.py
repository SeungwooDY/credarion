"""API endpoints for organization and supplier management."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, Supplier

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])


class OrgCreate(BaseModel):
    name: str
    reporting_currency: str = "RMB"


class OrgResponse(BaseModel):
    id: str
    name: str
    reporting_currency: str


class SupplierResponse(BaseModel):
    id: str
    vendor_code: str
    name: str
    currency: str | None = None
    is_cross_border: bool = False


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(
    body: OrgCreate,
    db: Session = Depends(get_db),
) -> OrgResponse:
    """Create a new organization."""
    org = Organization(name=body.name, reporting_currency=body.reporting_currency)
    db.add(org)
    db.commit()
    db.refresh(org)
    return OrgResponse(id=str(org.id), name=org.name, reporting_currency=org.reporting_currency)


@router.get("", response_model=list[OrgResponse])
async def list_orgs(db: Session = Depends(get_db)) -> list[OrgResponse]:
    """List all organizations."""
    orgs = db.query(Organization).all()
    return [
        OrgResponse(id=str(o.id), name=o.name, reporting_currency=o.reporting_currency)
        for o in orgs
    ]


@router.get("/{org_id}/suppliers", response_model=list[SupplierResponse])
async def list_suppliers(
    org_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[SupplierResponse]:
    """List all suppliers for an organization."""
    suppliers = db.query(Supplier).filter_by(org_id=org_id).all()
    return [
        SupplierResponse(
            id=str(s.id),
            vendor_code=s.vendor_code,
            name=s.name,
            currency=s.currency,
            is_cross_border=s.is_cross_border,
        )
        for s in suppliers
    ]
