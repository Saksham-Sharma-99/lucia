from collections.abc import Callable
from typing import Annotated, Any, Self

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession


class PageParams(BaseModel):
    page: int
    limit: int


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageParams:
    return PageParams(page=page, limit=limit)


Paging = Annotated[PageParams, Depends(page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    limit: int

    @classmethod
    def of(cls, items: list[T], total: int, paging: PageParams) -> Self:
        return cls(items=items, total=total, page=paging.page, limit=paging.limit)


async def fetch_page(
    session: AsyncSession,
    stmt: Select[*tuple[Any, ...]],
    paging: PageParams,
    *,
    scalars: bool = True,
) -> tuple[list[Any], int]:
    """One page of `stmt` and the total. `scalars=True` yields the first column (an entity for
    `select(Model)`); False yields rows. The count drops the select list, so correlated
    subqueries in it are not evaluated for the total; for the same reason `stmt` must not use
    DISTINCT or GROUP BY."""
    counted = stmt.with_only_columns(literal(1), maintain_column_froms=True).order_by(None)
    total = await session.scalar(select(func.count()).select_from(counted.subquery()))
    result = await session.execute(
        stmt.offset((paging.page - 1) * paging.limit).limit(paging.limit)
    )
    return list(result.scalars() if scalars else result.all()), total or 0


async def paginate[T](
    session: AsyncSession,
    stmt: Select[*tuple[Any, ...]],
    paging: PageParams,
    out: Callable[[Any], T],
    *,
    scalars: bool = True,
) -> Page[T]:
    rows, total = await fetch_page(session, stmt, paging, scalars=scalars)
    return Page.of([out(r) for r in rows], total, paging)
