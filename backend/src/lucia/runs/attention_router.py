import uuid

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.harness.answers import answer
from lucia.runs import schemas as s

router = api_router("attention", "/attention")


@router.post(
    "/{item_id}/answer",
    summary="Answer an attention item (first answer wins)",
    operation_id="answerAttention",
)
async def answer_item(
    item_id: uuid.UUID, body: s.AnswerIn, session: DbSession, user: CurrentUser
) -> s.StepResultOut:
    item = await answer(
        session, item_id, choice=body.choice, text=body.text, answered_by={"user_id": str(user.id)}
    )
    return s.StepResultOut.model_validate(item)
