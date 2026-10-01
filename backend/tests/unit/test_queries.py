import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from lucia.core.errors import ProblemError
from lucia.core.pagination import PageParams, fetch_page, paginate
from lucia.db.models import Firm
from lucia.db.queries import apply_patch, get_or_404, like_pattern, unique_or
from lucia.firms.schemas import FirmPatch
from tests.factories import ZERO


async def _firms(db: AsyncSession, n: int) -> None:
    for i in range(n):
        db.add(Firm(name=f"F{i}", slug=f"firm-{i}", timezone="UTC", color="#000000", settings={}))
    await db.commit()


@pytest.mark.parametrize(
    ("page", "limit", "names", "total"),
    [
        (1, 2, ["F0", "F1"], 3),
        (2, 2, ["F2"], 3),
        (3, 2, [], 3),
    ],
)
async def test_fetch_page_slices_and_counts(
    db: AsyncSession, page: int, limit: int, names: list[str], total: int
) -> None:
    await _firms(db, 3)
    rows, count = await fetch_page(
        db, select(Firm).order_by(Firm.name), PageParams(page=page, limit=limit)
    )
    assert [f.name for f in rows] == names and count == total


async def test_fetch_page_rows_mode_and_empty(db: AsyncSession) -> None:
    rows, count = await fetch_page(
        db, select(Firm.name, Firm.slug), PageParams(page=1, limit=5), scalars=False
    )
    assert (rows, count) == ([], 0)
    await _firms(db, 1)
    rows, _ = await fetch_page(
        db, select(Firm.name, Firm.slug), PageParams(page=1, limit=5), scalars=False
    )
    assert [tuple(r) for r in rows] == [("F0", "firm-0")]


async def test_paginate_maps_items(db: AsyncSession) -> None:
    await _firms(db, 2)
    page = await paginate(
        db, select(Firm).order_by(Firm.name), PageParams(page=1, limit=1), lambda f: f.slug
    )
    assert page.model_dump() == {"items": ["firm-0"], "total": 2, "page": 1, "limit": 1}


async def test_get_or_404(db: AsyncSession) -> None:
    with pytest.raises(ProblemError) as exc:
        await get_or_404(db, Firm, uuid.UUID(ZERO), "Firm")
    assert (exc.value.problem.status, exc.value.problem.detail) == (404, "Firm not found")


def test_apply_patch_skips_unset_none_and_excluded() -> None:
    firm = Firm(name="Old", color="#000000", timezone="UTC")
    apply_patch(
        firm, FirmPatch(name="New", color=None, timezone="Europe/Paris"), exclude={"timezone"}
    )
    assert (firm.name, firm.color, firm.timezone) == ("New", "#000000", "UTC")


async def test_fetch_page_counts_rows_with_correlated_subqueries(db: AsyncSession) -> None:
    await _firms(db, 3)
    other = aliased(Firm)
    sub = select(func.count()).where(other.id == Firm.id).scalar_subquery().label("n")
    rows, total = await fetch_page(
        db, select(Firm.slug, sub).order_by(Firm.slug), PageParams(page=2, limit=2), scalars=False
    )
    assert total == 3 and [tuple(r) for r in rows] == [("firm-2", 1)]


async def test_unique_or_maps_only_the_named_constraint(db: AsyncSession) -> None:
    await _firms(db, 1)
    taken = ProblemError(422, "Slug is taken")
    db.add(Firm(name="Dup", slug="firm-0", timezone="UTC", color="#000000", settings={}))
    with pytest.raises(ProblemError) as exc:
        async with unique_or(db, "firms_slug_key", taken):
            await db.flush()
    assert exc.value is taken
    db.add(Firm(name="Dup", slug="firm-0", timezone="UTC", color="#000000", settings={}))
    with pytest.raises(IntegrityError):
        async with unique_or(db, "some_other_constraint", taken):
            await db.flush()


@pytest.mark.parametrize(
    ("q", "pattern"),
    [
        ("abc", "%abc%"),
        (" a ", "%a%"),
        ("50%", "%50\\%%"),
        ("a_b", "%a\\_b%"),
        ("\\", "%\\\\%"),
    ],
)
def test_like_pattern_escapes(q: str, pattern: str) -> None:
    assert like_pattern(q) == pattern
