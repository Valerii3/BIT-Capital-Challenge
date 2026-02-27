from functools import lru_cache

from supabase import Client, create_client

from config import get_required_env


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    url = get_required_env("SUPABASE_URL")
    key = get_required_env("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)
