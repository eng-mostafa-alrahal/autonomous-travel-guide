from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, status

from app.api.dependencies import get_current_user_id, get_run_state_uc, get_session_service
from app.api.v1.schemas.session_schema import (
    SessionCreateRequest,
    SessionMessageItem,
    SessionMessagesResponse,
    SessionRenameRequest,
    SessionResponse,
)
from app.modules.agent_orchestration.application.dtos.agent_result import (
    visible_chat_history,
)
from app.modules.agent_orchestration.application.ports.agent_orchestrator_port import (
    IAgentOrchestrator,
)
from app.modules.sessions.use_cases.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new session",
    description="Create a conversation session for the authenticated user.",
)
async def create_session(
    body: Annotated[
        SessionCreateRequest,
        Body(description="Payload used to create a new session (title optional)."),
    ],
    user_id=Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = await service.create_session(user_id=user_id, title=body.title)
    return SessionResponse.model_validate(session)


@router.get(
    "/",
    response_model=list[SessionResponse],
    summary="List user sessions",
    description="Return all sessions owned by the authenticated user.",
)
async def list_sessions(
    user_id=Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service),
) -> list[SessionResponse]:
    sessions = await service.list_sessions(user_id=user_id)
    return [SessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get one session",
    description=(
        "Fetch a specific session by ID. "
        "The session must belong to the authenticated user."
    ),
)
async def get_session(
    session_id: Annotated[
        UUID,
        Path(
            description="Session UUIDv7 to retrieve.",
            examples=["019d92bc-2c73-74e6-814a-b647e46f0bf5"],
        ),
    ],
    user_id=Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = await service.get_session(session_id=session_id, user_id=user_id)
    return SessionResponse.model_validate(session)


@router.get(
    "/{session_id}/messages",
    response_model=SessionMessagesResponse,
    summary="Get session message history",
    description=(
        "Return the conversation transcript for a session from the LangGraph "
        "checkpointer (thread id == session id). "
        "Requires ownership. Internal memory-summary messages are omitted. "
        "Returns an empty list when the session has not been chatted yet."
    ),
)
async def get_session_messages(
    session_id: Annotated[
        UUID,
        Path(
            description="Session UUIDv7 whose history to load.",
            examples=["019d92bc-2c73-74e6-814a-b647e46f0bf5"],
        ),
    ],
    user_id=Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service),
    orchestrator: IAgentOrchestrator = Depends(get_run_state_uc),
    include_tools: Annotated[
        bool,
        Query(description="Include tool-result messages in the transcript."),
    ] = False,
    include_system: Annotated[
        bool,
        Query(description="Include system messages in the transcript."),
    ] = False,
) -> SessionMessagesResponse:
    await service.get_session(session_id=session_id, user_id=user_id)
    snapshot = await orchestrator.get_state(thread_id=str(session_id))
    visible = visible_chat_history(
        snapshot.messages,
        include_tools=include_tools,
        include_system=include_system,
    )
    return SessionMessagesResponse(
        session_id=session_id,
        messages=[
            SessionMessageItem(
                type=m.type,
                content=m.content,
                id=m.id,
                tool_calls=m.tool_calls,
            )
            for m in visible
        ],
    )


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Rename a session",
    description="Update the title of an existing session owned by the authenticated user.",
)
async def rename_session(
    session_id: Annotated[
        UUID,
        Path(
            description="Session UUIDv7 to rename.",
            examples=["019d92bc-2c73-74e6-814a-b647e46f0bf5"],
        ),
    ],
    body: Annotated[
        SessionRenameRequest,
        Body(description="Payload containing the new session title."),
    ],
    user_id=Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = await service.rename_session(session_id=session_id, user_id=user_id, title=body.title)
    return SessionResponse.model_validate(session)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session",
    description="Delete a session and its related data. Returns no body on success.",
)
async def delete_session(
    session_id: Annotated[
        UUID,
        Path(
            description="Session UUIDv7 to delete.",
            examples=["019d92bc-2c73-74e6-814a-b647e46f0bf5"],
        ),
    ],
    user_id=Depends(get_current_user_id),
    service: SessionService = Depends(get_session_service),
) -> None:
    await service.delete_session(session_id=session_id, user_id=user_id)
