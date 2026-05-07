import os
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]

app = FastAPI()
_client: TelegramClient | None = None
_lock = asyncio.Lock()


async def get_client() -> TelegramClient:
    global _client
    async with _lock:
        if _client is None or not _client.is_connected():
            _client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
            await _client.connect()
    return _client


class ParseRequest(BaseModel):
    invite_link: str
    limit: int = 30


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/parse")
async def parse_channel(req: ParseRequest):
    client = await get_client()

    # t.me/c/CHANNEL_ID → Telethon needs integer -100CHANNEL_ID
    invite = req.invite_link.strip()
    import re as _re
    m = _re.match(r'https?://t\.me/c/(\d+)', invite)
    channel_ref = int('-100' + m.group(1)) if m else invite

    try:
        entity = await client.get_entity(channel_ref)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot get channel: {str(e)}")

    try:
        messages = await client.get_messages(entity, limit=req.limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot fetch messages: {str(e)}")

    posts = []
    for msg in messages:
        if not msg.message and not msg.media:
            continue

        media_type = "text"
        if isinstance(msg.media, MessageMediaPhoto):
            media_type = "photo"
        elif isinstance(msg.media, MessageMediaDocument):
            mime = getattr(msg.media.document, "mime_type", "") or ""
            media_type = "video" if mime.startswith("video") else "document"

        if hasattr(entity, "username") and entity.username:
            post_url = f"https://t.me/{entity.username}/{msg.id}"
        else:
            post_url = f"https://t.me/c/{entity.id}/{msg.id}"

        posts.append({
            "postUrl": post_url,
            "text": msg.message or "",
            "views": msg.views or 0,
            "postedAt": msg.date.isoformat(),
            "mediaType": media_type,
            "mediaUrl": "",
        })

    if not posts:
        raise HTTPException(status_code=404, detail="No posts found")

    sorted_views = sorted(p["views"] for p in posts)
    mid = len(sorted_views) // 2
    median = sorted_views[mid] if len(sorted_views) % 2 != 0 else (sorted_views[mid - 1] + sorted_views[mid]) // 2
    threshold = round(median * 0.7)

    return {
        "username": getattr(entity, "username", None) or str(entity.id),
        "channelTitle": getattr(entity, "title", "") or "",
        "posts": posts,
        "postCount": len(posts),
        "median": median,
        "threshold": threshold,
    }
