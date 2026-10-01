"""Structural diff of two configs, as JSON-pointer paths."""

from typing import Any, Literal

from pydantic import BaseModel

Op = Literal["add", "remove", "change"]


class DiffEntry(BaseModel):
    path: str
    op: Op
    before: Any = None
    after: Any = None


def diff(before: Any, after: Any, path: str = "") -> list[DiffEntry]:
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[DiffEntry] = []
        for key in sorted(before.keys() | after.keys()):
            sub = f"{path}/{key}"
            if key not in after:
                out.append(DiffEntry(path=sub, op="remove", before=before[key]))
            elif key not in before:
                out.append(DiffEntry(path=sub, op="add", after=after[key]))
            else:
                out += diff(before[key], after[key], sub)
        return out
    if isinstance(before, list) and isinstance(after, list):
        out = []
        for i in range(max(len(before), len(after))):
            sub = f"{path}/{i}"
            if i >= len(after):
                out.append(DiffEntry(path=sub, op="remove", before=before[i]))
            elif i >= len(before):
                out.append(DiffEntry(path=sub, op="add", after=after[i]))
            else:
                out += diff(before[i], after[i], sub)
        return out
    if before != after:
        return [DiffEntry(path=path or "/", op="change", before=before, after=after)]
    return []
