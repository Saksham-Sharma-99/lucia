"""A faithful `conversations.replies`: like Slack, metadata only with include_all_metadata."""

from typing import Any

import respx
from httpx import Request, Response

API = "https://slack.com/api"


def replies(*messages: dict[str, Any]) -> respx.Route:
    def answer(request: Request) -> Response:
        with_metadata = request.url.params.get("include_all_metadata") == "true"
        shown = [
            m if with_metadata else {k: v for k, v in m.items() if k != "metadata"}
            for m in messages
        ]
        return Response(200, json={"ok": True, "messages": shown})

    return respx.get(f"{API}/conversations.replies").mock(side_effect=answer)
