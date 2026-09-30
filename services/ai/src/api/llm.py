"""LLM チャット/補完エンドポイント"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import scope_org
from ..models.base import get_db
from ..schemas import (
    ChatRequest,
    CompletionRequest,
)
from ..services.llm_service import MockLLMProvider, OpenAICompatibleProvider
from ..services.prompt_service import PromptService

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_llm_provider() -> OpenAICompatibleProvider | MockLLMProvider:
    from ..config import get_settings

    s = get_settings()
    if s.LLM_API_KEY:
        return OpenAICompatibleProvider()
    return MockLLMProvider()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Fail closed before any work (and outside the template try/except below,
    # which would otherwise swallow the 403).
    org_id = scope_org(token_data)
    llm = _get_llm_provider()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    if body.prompt_template_id:
        try:
            template = await PromptService.get_template(
                db, body.prompt_template_id, org_id
            )
            if template:
                from jinja2 import Template

                variables = body.variables or {}
                user_content = Template(template.user_prompt_template).render(
                    **variables
                )
                messages = [
                    {"role": "system", "content": template.system_prompt},
                ] + messages
                if user_content.strip():
                    messages.append({"role": "user", "content": user_content})
        except Exception:
            logger.exception("Failed to apply prompt template")

    kwargs: dict[str, object] = {}
    if body.model:
        kwargs["model"] = body.model
    if body.temperature is not None:
        kwargs["temperature"] = body.temperature
    if body.max_tokens is not None:
        kwargs["max_tokens"] = body.max_tokens

    try:
        response_text = await llm.complete(messages, **kwargs)
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    return {
        "success": True,
        "data": {
            "message": {"role": "assistant", "content": response_text},
            "conversation_id": body.conversation_id,
            "usage": None,
        },
    }


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Fail closed before any work (and outside the template try/except below,
    # which would otherwise swallow the 403).
    org_id = scope_org(token_data)
    llm = _get_llm_provider()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    if body.prompt_template_id:
        try:
            template = await PromptService.get_template(
                db, body.prompt_template_id, org_id
            )
            if template:
                from jinja2 import Template

                variables = body.variables or {}
                user_content = Template(template.user_prompt_template).render(
                    **variables
                )
                messages = [
                    {"role": "system", "content": template.system_prompt},
                ] + messages
                if user_content.strip():
                    messages.append({"role": "user", "content": user_content})
        except Exception:
            logger.exception("Failed to apply prompt template")

    kwargs: dict[str, object] = {}
    if body.model:
        kwargs["model"] = body.model
    if body.temperature is not None:
        kwargs["temperature"] = body.temperature
    if body.max_tokens is not None:
        kwargs["max_tokens"] = body.max_tokens

    async def event_generator():
        try:
            async for chunk in llm.stream_complete(messages, **kwargs):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if hasattr(llm, "close"):
                await llm.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/complete")
async def complete(
    body: CompletionRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    template = await PromptService.get_template(db, body.prompt_template_id, org_id)
    if not template:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "プロンプトテンプレートが見つかりません。",
            },
        )

    from jinja2 import Template

    user_content = Template(template.user_prompt_template).render(
        **(body.variables or {})
    )

    messages = [
        {"role": "system", "content": template.system_prompt},
        {"role": "user", "content": user_content},
    ]

    kwargs = {
        "model": body.model or template.model,
        "temperature": body.temperature
        if body.temperature is not None
        else template.temperature,
        "max_tokens": body.max_tokens or template.max_tokens,
    }

    llm = _get_llm_provider()
    try:
        response_text = await llm.complete(messages, **kwargs)
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    return {
        "success": True,
        "data": {
            "content": response_text,
            "prompt_template_id": str(body.prompt_template_id),
            "usage": None,
        },
    }
