import os
from datetime import datetime, timedelta, timezone

import topscorers_dashboard as dashboard

from .bid_service import reconcile_automatic_bids, upsert_automatic_bid

_session = None


def _data(payload):
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def _items(payload):
    value = _data(payload)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        players = value.get("players")
        return players if isinstance(players, list) else [value]
    return []


def _request(session, path):
    response = session.get(f"{dashboard.BASE}{path}", timeout=20)
    response.raise_for_status()
    return response.json()


def _player(item):
    nested = item.get("player") if isinstance(item, dict) else None
    return nested if isinstance(nested, dict) else (item if isinstance(item, dict) else {})


def _player_id(item):
    player = _player(item)
    return player.get("id") or player.get("player_id")


def _team_name(player):
    team = player.get("team") or {}
    return (team.get("acronym") or team.get("name") or "") if isinstance(team, dict) else str(team or "")


def _own_offer(transfer, username):
    offers = transfer.get("offers") if isinstance(transfer, dict) else []
    for offer in offers if isinstance(offers, list) else []:
        if str(offer.get("username") or "").strip().casefold() == username.casefold():
            return offer
    return None


def sync_market_bids(session=None, now=None):
    """Import Droken's visible offers and infer completed auction outcomes."""
    global _session
    username = (os.getenv("TOPS_USERNAME") or "Droken").strip()
    now = now or datetime.now(timezone.utc)
    if session is None:
        if _session is None:
            _session = dashboard.login_session()
        session = _session
    try:
        transfers = _items(_request(session, f"/api/user/leagues/{dashboard.LEAGUE_ID}/transfers"))
        roster = _items(_request(session, f"/api/user/teams/{dashboard.TEAM_ID}/players"))
    except Exception:
        if session is _session:
            _session = None
        raise

    active_ids = set()
    imported = []
    for transfer in transfers:
        transfer_id = transfer.get("id")
        if transfer_id is None:
            continue
        active_ids.add(str(transfer_id))
        offer = _own_offer(transfer, username)
        if not offer:
            continue
        player = _player(transfer)
        expires = transfer.get("expires_in")
        expires_at = ""
        try:
            expires_at = (now + timedelta(seconds=max(0, float(expires)))).isoformat()
        except (TypeError, ValueError):
            pass
        imported.append(upsert_automatic_bid({
            "transfer_id": transfer_id,
            "player_id": _player_id(transfer),
            "player_name": " ".join(str(player.get(key) or "") for key in ("firstname", "lastname")).strip(),
            "team": _team_name(player),
            "position_family": dashboard.pos_family_label(player.get("position_id") or player.get("position")),
            "market_price": transfer.get("price") or player.get("marketvalue") or "",
            "bid_amount": offer.get("price") or "",
            "expires_at": expires_at,
        }))

    roster_ids = {_player_id(item) for item in roster if _player_id(item) is not None}
    resolved = reconcile_automatic_bids(active_ids, roster_ids, now=now)
    return {"ok": True, "active_transfers": len(active_ids), "imported": len(imported), "resolved": len(resolved), "items": imported, "resolved_items": resolved}
