# backend/app/bid_service.py
import csv
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

BID_HISTORY_PATH = Path(os.getenv("BID_HISTORY_CSV", "/data/bid_history.csv"))
_FIELDS = [
    "id", "created_at", "updated_at", "player_id", "player_name", "team",
    "position_family", "market_price", "bid_amount", "result", "final_price", "notes",
    "source", "transfer_id", "expires_at", "last_seen_at",
]
_lock = threading.Lock()


def _normalize_row(row):
    return {key: row.get(key, "") for key in _FIELDS}


def _read_rows():
    if not BID_HISTORY_PATH.exists():
        return []
    with BID_HISTORY_PATH.open("r", encoding="utf-8", newline="") as handle:
        return [_normalize_row(row) for row in csv.DictReader(handle)]


def _write_rows(rows):
    BID_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with BID_HISTORY_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_normalize_row(row) for row in rows)


def list_bids():
    with _lock:
        return _read_rows()


def save_bid(payload):
    now = datetime.now(timezone.utc).isoformat()
    row = {key: "" for key in _FIELDS}
    row.update({key: payload.get(key, "") for key in _FIELDS if key in payload})
    row["id"] = row["id"] or uuid.uuid4().hex
    row["created_at"] = row["created_at"] or now
    row["updated_at"] = now
    row["result"] = str(row.get("result") or "pending").lower()
    with _lock:
        rows = _read_rows()
        rows.append(row)
        _write_rows(rows)
    return row


def upsert_automatic_bid(payload):
    """Create or refresh one bid detected in the TopScorers market."""
    transfer_id = str(payload.get("transfer_id") or "")
    if not transfer_id:
        raise ValueError("transfer_id is required for an automatic bid")
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        rows = _read_rows()
        found = next((row for row in rows if row.get("source") == "market-auto" and str(row.get("transfer_id")) == transfer_id), None)
        if found is None:
            found = {key: "" for key in _FIELDS}
            found.update({key: payload.get(key, "") for key in _FIELDS if key in payload})
            found.update(id=uuid.uuid4().hex, created_at=now, result="pending", source="market-auto")
            rows.append(found)
        elif found.get("result") == "pending":
            for key in ("player_id", "player_name", "team", "position_family", "market_price", "bid_amount", "expires_at"):
                if key in payload:
                    found[key] = payload[key]
        found["updated_at"] = now
        found["last_seen_at"] = now
        _write_rows(rows)
        return dict(found)


def reconcile_automatic_bids(active_transfer_ids, roster_player_ids, now=None):
    """Close only auto-detected pending bids; manual entries are never guessed."""
    active = {str(value) for value in active_transfer_ids}
    roster = {str(value) for value in roster_player_ids}
    now_dt = now or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    changed = []
    with _lock:
        rows = _read_rows()
        for row in rows:
            if row.get("source") != "market-auto" or row.get("result") != "pending":
                continue
            player_id = str(row.get("player_id") or "")
            transfer_id = str(row.get("transfer_id") or "")
            if player_id and player_id in roster:
                row["result"] = "won"
                row["final_price"] = row.get("bid_amount") or ""
                row["notes"] = "Résultat détecté automatiquement : joueur présent dans Droken."
            elif transfer_id and transfer_id not in active and _is_expired(row.get("expires_at"), now_dt):
                row["result"] = "lost"
                row["notes"] = "Résultat détecté automatiquement : vente terminée, joueur absent de Droken."
            else:
                continue
            row["updated_at"] = now_iso
            changed.append(dict(row))
        if changed:
            _write_rows(rows)
    return changed


def _is_expired(value, now):
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= now
    except (TypeError, ValueError):
        return False


def update_result(bid_id, result, final_price=None, notes=None):
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        rows = _read_rows()
        found = None
        for row in rows:
            if row.get("id") != bid_id:
                continue
            row["result"] = str(result).lower()
            row["updated_at"] = now
            if final_price is not None:
                row["final_price"] = final_price
            if notes is not None:
                row["notes"] = notes
            found = row
            break
        if found is None:
            return None
        _write_rows(rows)
        return found
