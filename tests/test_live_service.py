import unittest

from backend.app import live_service


class LiveServiceTests(unittest.TestCase):
    def test_normalizes_live_player_events(self):
        player = {
            "id": 42,
            "firstname": "Test",
            "lastname": "Player",
            "position_id": 3,
            "team": {"acronym": "LHC"},
            "live_points": 87,
            "live_stats": {
                "goals": 1,
                "assists": 1,
                "shots_on_goal": 4,
                "blocked_shots": 2,
                "penalty_minutes": 2,
                "plus_minus": 1,
            },
        }
        row = live_service._player_row(player, {"42"}, stats_source=True)
        self.assertEqual(row["name"], "Test Player")
        self.assertEqual(row["position"], "Attaquant")
        self.assertTrue(row["lined_up"])
        self.assertEqual(row["live_points"], 87)
        self.assertEqual(row["stats"]["assists"], 1)
        self.assertEqual(row["stats"]["penalty_minutes"], 2)

    def test_player_name_is_not_taken_from_nested_team(self):
        roster_player = {"id": 42, "firstname": "Connor", "lastname": "Hughes", "position_name": "C"}
        live_player = {"id": 42, "team": {"name": "SC Bern", "acronym": "SCB"}, "live_points": 12}
        row = live_service._player_row({**roster_player, **live_player}, {"42"}, stats_source=True)
        self.assertEqual(row["name"], "Connor Hughes")
        self.assertEqual(row["team"], "SCB")
        self.assertEqual(row["position"], "C")

    def test_official_scoring_contains_positive_and_discipline_events(self):
        scoring = live_service.OFFICIAL_SCORING
        self.assertEqual(scoring["goal_forward"], 60)
        self.assertEqual(scoring["assist_forward"], 40)
        self.assertEqual(scoring["blocked_shot"], 10)
        self.assertEqual(scoring["penalty_2_minutes"], -10)
        self.assertEqual(scoring["match_penalty"], -125)

    def test_extracts_current_lineup_ids(self):
        payload = {
            "lineup": [
                {"position_id": 1, "current": 12},
                {"position_id": 2, "current": {"id": 34}},
            ]
        }
        self.assertEqual(live_service._active_player_ids(payload), {"12", "34"})


if __name__ == "__main__":
    unittest.main()
