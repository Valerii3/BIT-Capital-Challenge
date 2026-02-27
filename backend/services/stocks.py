from typing import Any, Dict, List, Optional

from supabase import Client


def list_stocks(supabase: Client) -> List[Dict[str, Any]]:
    resp = (
        supabase.table("stocks")
        .select("*")
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def create_stock(supabase: Client, name: str) -> Dict[str, Any]:
    resp = (
        supabase.table("stocks")
        .insert(
            {
                "name": name,
                "status": "enriching",
                "enrich_progress": {"step": "description"},
            }
        )
        .execute()
    )
    if not resp.data:
        raise RuntimeError("Failed to create stock")
    # Insert returns a list; we inserted one row
    return resp.data[0]


def delete_stock(supabase: Client, stock_id: str) -> None:
    supabase.table("stocks").delete().eq("id", stock_id).execute()


def get_stock(supabase: Client, stock_id: str) -> Optional[Dict[str, Any]]:
    resp = supabase.table("stocks").select("*").eq("id", stock_id).single().execute()
    return resp.data
