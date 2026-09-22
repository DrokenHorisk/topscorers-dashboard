import unittest

from backend.app import live_service


class LiveServiceTests(unittest.TestCase):
    def test_normalizes_real_live_endpoint_game_shape(self):
        payload = {
            "games": [{
                "home_team": {"acronym": "LHC"},
                "away_team": {"acronym": "SCB"},
                "begin": "2026-09-22T19:45:00+02:00",
                "score": "2:1",
                "status": 2,
                "status_key": "live",
                "status_name": "2e tiers",
                "is_live": True,
            }]
        }
        games = live_service._normalize_games(payload)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["home_score"], "2")
        self.assertEqual(games[0]["away_score"], "1")
        self.assertEqual(games[0]["status"], "2e tiers")
        self.assertTrue(games[0]["live"])

    def test_normalizes_games_data_list_fallback(self):
        payload = {"data": [{"home": "LHC", "away": "SCB", "score": "0-0"}]}
        games = live_service._normalize_games(payload)
        self.assertEqual(games[0]["home_score"], "0")
        self.assertEqual(games[0]["away_score"], "0")

    def test_reads_badges_from_live_player(self):
        player = {
            "id": 42,
            "firstname": "Test",
            "lastname": "Player",
            "position_id": 3,
            "points": 65,
            "badges": {"goals": 1, "shots_on_goal": 1},
        }
        row = live_service._player_row(player, {"42"}, stats_source=True)
        self.assertEqual(row["live_points"], 65)
        self.assertEqual(row["stats"]["goals"], 1)
        self.assertEqual(row["stats"]["shots_on_goal"], 1)

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
        self.assertEqual(row["position"], "Attaquant")

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

    def test_direct_pick_does_not_leak_nested_live_metadata(self):
        payload = {
            "next_update_in_seconds": 15,
            "socket": {"next_update_in_seconds": 999},
        }
        self.assertEqual(
            live_service._direct_pick(payload, ("next_update_in_seconds",)),
            15,
        )


if __name__ == "__main__":
    unittest.main()
