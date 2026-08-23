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
]
_lock = threading.Lock()


def _read_rows():
    if not BID_HISTORY_PATH.exists():
        return []
    with BID_HISTORY_PATH.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
    BID_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        rows = _read_rows()
        rows.append(row)
        with BID_HISTORY_PATH.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    return row


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
        with BID_HISTORY_PATH.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return found
