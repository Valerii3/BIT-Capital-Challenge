from typing import Any, Dict, List, Literal, Optional

from supabase import Client

SortOption = Literal["recent", "volume_desc", "volume_asc", "score_desc", "score_asc"]


def list_events(
    supabase: Client,
    *,
    search: Optional[str],
    active: Optional[bool],
    prefilter_passed: Optional[bool],
    impact_types: List[str],
    stock_ids: List[str],
    sort: SortOption,
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    event_ids: Optional[List[str]] = None
    if stock_ids:
        mappings_resp = (
            supabase.table("event_stock_mappings")
            .select("event_id")
            .in_("stock_id", stock_ids)
            .eq("affects", True)
            .execute()
        )
        event_ids = list({row["event_id"] for row in (mappings_resp.data or []) if row.get("event_id")})
        if not event_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    if prefilter_passed is not None:
        ef_resp = (
            supabase.table("event_filtering")
            .select("event_id")
            .eq("prefilter_passed", prefilter_passed)
            .execute()
        )
        ef_ids = [row["event_id"] for row in (ef_resp.data or [])]
        if event_ids is not None:
            event_ids = list(set(event_ids) & set(ef_ids))
        else:
            event_ids = ef_ids
        if not event_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    if impact_types:
        ef_resp = (
            supabase.table("event_filtering")
            .select("event_id")
            .in_("impact_type", impact_types)
            .execute()
        )
        ef_ids = [row["event_id"] for row in (ef_resp.data or [])]
        if event_ids is not None:
            event_ids = list(set(event_ids) & set(ef_ids))
        else:
            event_ids = ef_ids
        if not event_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    base_query = (
        supabase.table("polymarket_events")
        .select(
            "id,title,description,active,volume,updated_at,first_seen_at,"
            "event_filtering(prefilter_passed,relevant,relevance_score,impact_type,theme_labels),"
            "polymarket_markets(id,question,outcomes,outcome_prices,volume_num)",
            count="exact",
        )
    )

    if event_ids is not None:
        base_query = base_query.in_("id", event_ids)
    if search:
        base_query = base_query.ilike("title", f"%{search}%")
    if active is not None:
        base_query = base_query.eq("active", active)

    if sort in ("score_desc", "score_asc"):
        resp = base_query.execute()
        rows = resp.data or []
        reverse = sort == "score_desc"
        rows.sort(
            key=lambda row: (
                ((row.get("event_filtering") or {}).get("relevance_score"))
                if isinstance(row.get("event_filtering"), dict)
                else -1
            )
            if ((row.get("event_filtering") or {}).get("relevance_score") is not None)
            else -1,
            reverse=reverse,
        )
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "items": rows[start:end],
            "total": len(rows),
            "page": page,
            "page_size": page_size,
        }

    if sort == "volume_asc":
        order_col = "volume"
        ascending = True
    elif sort == "volume_desc":
        order_col = "volume"
        ascending = False
    else:
        order_col = "updated_at"
        ascending = False

    start = (page - 1) * page_size
    end = start + page_size - 1
    resp = base_query.order(order_col, desc=not ascending).range(start, end).execute()
    return {
        "items": resp.data or [],
        "total": resp.count or 0,
        "page": page,
        "page_size": page_size,
    }
