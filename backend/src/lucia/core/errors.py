"""RFC 7807 problem+json errors with JSON-pointer field paths."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class FieldError(BaseModel):
    path: str
    code: str
    message: str


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    errors: list[FieldError] = []


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        errors: list[FieldError] | None = None,
        type_: str = "about:blank",
    ) -> None:
        super().__init__(detail or title)
        self.problem = Problem(
            type=type_, title=title, status=status, detail=detail, errors=errors or []
        )


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "Not found", f"{what} not found")


def conflict(detail: str) -> ProblemError:
    return ProblemError(409, "Conflict", detail)


def invalid(errors: list[FieldError], detail: str = "Validation failed") -> ProblemError:
    return ProblemError(422, "Unprocessable entity", detail, errors)


def to_pointer(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return "/" + "/".join(parts) if parts else ""


def _response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(exclude_none=True), status_code=problem.status, media_type=PROBLEM_JSON
    )


def to_problem(exc: Exception) -> Problem:
    if isinstance(exc, ProblemError):
        return exc.problem
    if isinstance(exc, RequestValidationError):
        errors = [
            FieldError(path=to_pointer(e["loc"]), code=e["type"], message=e["msg"])
            for e in exc.errors()
        ]
        return Problem(title="Unprocessable entity", status=422, errors=errors)
    if isinstance(exc, StarletteHTTPException):
        return Problem(title=str(exc.detail), status=exc.status_code)
    raise exc


async def _handle(_: Request, exc: Exception) -> JSONResponse:
    return _response(to_problem(exc))


def install_error_handlers(app: FastAPI) -> None:
    for exc_type in (ProblemError, RequestValidationError, StarletteHTTPException):
        app.add_exception_handler(exc_type, _handle)


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": Problem, "description": "Not authenticated"},
    404: {"model": Problem, "description": "Not found"},
    409: {"model": Problem, "description": "Conflict"},
    422: {"model": Problem, "description": "Validation failed"},
}
