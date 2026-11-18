"""Shared route dependencies and lookups."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Base

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_or_404[T: Base](session: AsyncSession, model: type[T], object_id: str) -> T:
    row = await session.get(model, object_id)
    if row is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return row
