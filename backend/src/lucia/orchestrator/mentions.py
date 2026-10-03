import re
from collections.abc import Iterable


def parse(text: str, handles: Iterable[str]) -> list[str]:
    """Handles @mentioned in the text, in order; longest handle first (ORCHESTRATOR_SPEC §5.1)."""
    known = sorted(set(handles), key=len, reverse=True)
    if not known:
        return []
    pattern = re.compile(rf"(?<![\w@])@({'|'.join(map(re.escape, known))})(?![\w-])")
    return list(dict.fromkeys(pattern.findall(text)))
