"""HTTP routes. Everything is mounted under `/api`."""

from fastapi import APIRouter, Depends

from app.core.security import current_user

from . import (
    demo,
    deployments,
    docs,
    events,
    integrations,
    investigations,
    notifications,
    overview,
    system,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(docs.router)
api_router.include_router(events.public_router)

_protected = APIRouter(dependencies=[Depends(current_user)])
for module in (overview, deployments, investigations, integrations, notifications, events, demo):
    _protected.include_router(module.router)
api_router.include_router(_protected)
