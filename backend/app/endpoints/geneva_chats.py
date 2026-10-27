"""IS-98: named Geneva chats and their history. Scoped per RM by header `X-RM-Id` (same convention as the IPS chat endpoints)."""
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core import geneva_chats as store
from app.core.geneva_chats import ChatNotFoundError, HistoryUnavailableError

router = APIRouter(prefix="/geneva/chats", tags=["geneva-chats"])

UNAVAILABLE = "Chat history is unavailable."


def _rm(x_rm_id: Optional[str], rm_id: Optional[str]) -> str:
    return ((x_rm_id or rm_id or "").strip()[:80]) or store.DEFAULT_RM


def _down() -> JSONResponse:
    return JSONResponse({"detail": UNAVAILABLE, "historyAvailable": False, "chats": []}, status_code=503)


class CreateChat(BaseModel):
    id: str = Field(min_length=1, max_length=120)


class AppendMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1)


@router.get("")
async def list_chats(x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)):
    try:
        chats = await store.list_chats(_rm(x_rm_id, rm_id))
    except HistoryUnavailableError:
        return _down()
    return {"chats": chats, "historyAvailable": True}


@router.post("")
async def create_chat(body: CreateChat, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)):
    try:
        chat = await store.create_chat(_rm(x_rm_id, rm_id), body.id)
    except HistoryUnavailableError:
        return _down()
    except ChatNotFoundError:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {**chat, "historyAvailable": True}


@router.get("/{chat_id}/messages")
async def get_messages(chat_id: str, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)):
    try:
        data = await store.get_messages(_rm(x_rm_id, rm_id), chat_id)
    except HistoryUnavailableError:
        return _down()
    except ChatNotFoundError:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {**data, "historyAvailable": True}


@router.post("/{chat_id}/messages")
async def append_message(chat_id: str, body: AppendMessage, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)):
    try:
        chat = await store.append_message(_rm(x_rm_id, rm_id), chat_id, body.role, body.text)
    except HistoryUnavailableError:
        return _down()
    except ChatNotFoundError:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {**chat, "historyAvailable": True}
