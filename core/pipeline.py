"""The whole import in one call: text -> messages -> peers -> map points -> database.

Used by the Import page and by scripts/import_file.py.
"""
from core import db, geo
from core.extract import build_peers, rules_extractor
from core.ingest import find_linkedin_urls, parse_paste

# Rough Claude cost per message, measured on the real sample (82 messages ≈ $0.29 on Opus 5.5).
CLAUDE_COST_PER_MESSAGE = 0.0035


def import_text(text: str, engine: str = "claude", on_progress=None) -> dict:
    """Import pasted Discord text. engine: "claude" or "rules"."""
    return import_messages(parse_paste(text), engine, on_progress)


def import_messages(messages: list[dict], engine: str = "claude", on_progress=None) -> dict:
    """Save messages, extract the ones not seen before, put peers on the map, save them.

    Only messages not seen before are extracted, so re-importing an overlapping
    paste costs nothing extra. Returns a summary for the UI.
    """
    db.init_db()
    new_messages = db.save_messages(messages)
    pending = db.pending_messages()

    cost = None
    if engine == "claude" and pending:
        from core.claude_extract import ClaudeExtractor  # imported here so "rules" works without a key
        extractor = ClaudeExtractor(on_progress=on_progress)
    else:
        extractor = rules_extractor

    saved = {p["discord_handle"]: p for p in db.list_peers()}
    peers = build_peers(pending, extractor=extractor, saved=saved)
    if engine == "claude" and pending:
        cost = extractor.estimated_cost

    placed = 0
    for peer in peers:
        add_map_point(peer)
        placed += peer.get("lat") is not None
        db.save_peer(peer)
    db.mark_processed([m["id"] for m in pending])

    return {
        "messages_in_paste": len(messages),
        "new_messages": new_messages,
        "extracted": len(pending),
        "peers_updated": len(peers),
        "on_map": placed,
        "need_review": sum(p["needs_review"] for p in peers),
        "cost_usd": cost,
    }


def approve(peer_id: int, edits: dict) -> None:
    """Save your corrections from the Review screen and lock the record.

    - A LinkedIn link is cleaned up (or rejected if it isn't a profile link).
    - If the place changed, the map point is recalculated.
    - reviewed=1 means later imports won't overwrite your edits.
    """
    peer = db.get_peer(peer_id)
    edits = {k: (v.strip() if isinstance(v, str) else v) or None for k, v in edits.items()}
    for list_field in ("skills", "open_to"):
        if list_field in edits:
            edits[list_field] = edits[list_field] or []

    if edits.get("linkedin_url"):
        urls = find_linkedin_urls(edits["linkedin_url"])
        if not urls:
            raise ValueError("That doesn't look like a LinkedIn profile link (linkedin.com/in/…).")
        edits["linkedin_url"] = urls[0]

    place_fields = ("city", "region", "country")
    if any(f in edits and edits[f] != peer.get(f) for f in place_fields):
        place = {f: edits.get(f, peer.get(f)) for f in place_fields}
        moved = {**place, "lat": None, "lon": None, "location_raw": None}
        add_map_point(moved)
        edits["lat"], edits["lon"] = moved.get("lat"), moved.get("lon")

    db.update_peer(peer_id, **edits, reviewed=1, needs_review=0, review_reason=None)


def preview(messages: list[dict]) -> dict:
    """What an import would do, before spending anything."""
    db.init_db()
    known = db.known_message_ids([m["id"] for m in messages])
    new = [m for m in messages if m["id"] not in known]
    pending = db.message_counts()["total"] - db.message_counts()["processed"]
    to_extract = len(new) + pending
    return {
        "messages": len(messages),
        "new": len(new),
        "already_imported": len(messages) - len(new),
        "to_extract": to_extract,
        "authors": len({m["author_handle"] for m in new}),
        "estimated_cost": round(to_extract * CLAUDE_COST_PER_MESSAGE, 2),
    }


def add_map_point(peer: dict) -> None:
    """Fill lat/lon (and city/region/country when missing) from the peer's location."""
    if peer.get("lat") is not None:
        return
    if peer.get("city") or peer.get("region") or peer.get("country"):
        point = geo.geocode(peer.get("city"), peer.get("region"), peer.get("country"))
        if point is None and peer.get("location_raw"):
            point = geo.geocode(raw=peer["location_raw"])
    elif peer.get("location_raw"):
        point = geo.geocode(raw=peer["location_raw"])
    else:
        point = None
    if point is None:
        return
    peer["lat"], peer["lon"] = point["lat"], point["lon"]
    for key in ("city", "region", "country"):
        if not peer.get(key) and point.get(key):
            peer[key] = point[key]
