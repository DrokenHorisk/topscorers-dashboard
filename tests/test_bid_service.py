import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import bid_service


class BidServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(bid_service, "BID_HISTORY_PATH", Path(self.tempdir.name) / "bids.csv")
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.tempdir.cleanup()

    def test_auto_bid_is_idempotent_and_updates_amount(self):
        first = bid_service.upsert_automatic_bid({"transfer_id": 7, "player_id": 9, "player_name": "Kevin Pasche", "bid_amount": 621999})
        second = bid_service.upsert_automatic_bid({"transfer_id": 7, "player_id": 9, "player_name": "Kevin Pasche", "bid_amount": 630000})
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(bid_service.list_bids()), 1)
        self.assertEqual(second["bid_amount"], 630000)

    def test_auto_bid_becomes_won_when_player_joins_roster(self):
        bid_service.upsert_automatic_bid({"transfer_id": 7, "player_id": 9, "bid_amount": 621999})
        changed = bid_service.reconcile_automatic_bids(set(), {9})
        self.assertEqual(changed[0]["result"], "won")
        self.assertEqual(changed[0]["final_price"], "621999")

    def test_auto_bid_becomes_lost_after_transfer_disappears(self):
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        bid_service.upsert_automatic_bid({"transfer_id": 7, "player_id": 9, "bid_amount": 621999, "expires_at": expired})
        changed = bid_service.reconcile_automatic_bids(set(), set())
        self.assertEqual(changed[0]["result"], "lost")

    def test_missing_active_transfer_is_not_lost_before_expiry(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        bid_service.upsert_automatic_bid({"transfer_id": 7, "player_id": 9, "bid_amount": 621999, "expires_at": future})
        self.assertEqual(bid_service.reconcile_automatic_bids(set(), set()), [])

    def test_manual_pending_bid_is_not_auto_resolved(self):
        bid_service.save_bid({"player_name": "Manuel", "market_price": 1, "bid_amount": 2})
        self.assertEqual(bid_service.reconcile_automatic_bids(set(), set()), [])
        self.assertEqual(bid_service.list_bids()[0]["result"], "pending")


if __name__ == "__main__":
    unittest.main()
