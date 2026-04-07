from typing import Optional
from supabase import acreate_client, AsyncClient
from .config import settings

_client: Optional[AsyncClient] = None


async def get_db() -> AsyncClient:
    global _client
    if _client is None:
        _client = await acreate_client(settings.supabase_url, settings.supabase_key)
    return _client
