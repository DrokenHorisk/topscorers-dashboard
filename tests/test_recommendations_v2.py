import sys
import types
import unittest
from pathlib import Path

import pandas as pd

sys.modules.setdefault("requests", types.SimpleNamespace(Session=object))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import topscorers_dashboard as dashboard


class RecommendationV2Tests(unittest.TestCase):
    def setUp(self):
        self.roster = pd.DataFrame([
            {"Joueur": "Centre faible", "Poste": "C", "Pts moy.": 3.0, "Pts moy. (saison)": 3.0, "Étranger": ""},
            {"Joueur": "Ailier faible", "Poste": "W", "Pts moy.": 2.5, "Pts moy. (saison)": 2.5, "Étranger": ""},
            {"Joueur": "Défenseur faible", "Poste": "D", "Pts moy.": 2.0, "Pts moy. (saison)": 2.0, "Étranger": ""},
            {"Joueur": "Gardien faible", "Poste": "G", "Pts moy.": 4.0, "Pts moy. (saison)": 4.0, "Étranger": ""},
        ])
        self.market = pd.DataFrame([
            {
                "Joueur": "Centre star", "Poste": "C", "Prix": 800_000, "Valeur marchée": 1_200_000,
                "Pts moy.": 7.0, "Pts moy. (saison)": 7.2, "Pts moy. N-1": 6.8, "Pts moy. N-2": 6.5,
                "Matchs (saison)": 22, "Matchs (équipe)": 24, "Team PtsAvg": 4.2,
                "MV 90 j": 1_150_000, "MV min 365 j": 900_000, "MV max 365 j": 1_400_000,
                "Décote (%)": 33.3, "Décote vs max 365 (%)": 42.8, "Momentum 30 j (%)": 8.0,
                "Étranger": "", "Expire dans (s)": 7200, "AlphaScore": 90,
            },
            {
                "Joueur": "Ailier solide", "Poste": "W", "Prix": 700_000, "Valeur marchée": 850_000,
                "Pts moy.": 5.5, "Pts moy. (saison)": 5.6, "Pts moy. N-1": 5.4, "Pts moy. N-2": 5.0,
                "Matchs (saison)": 20, "Matchs (équipe)": 24, "Team PtsAvg": 4.0,
                "MV 90 j": 820_000, "MV min 365 j": 650_000, "MV max 365 j": 950_000,
                "Décote (%)": 17.6, "Décote vs max 365 (%)": 26.3, "Momentum 30 j (%)": 2.0,
                "Étranger": "", "Expire dans (s)": 18000, "AlphaScore": 75,
            },
            {
                "Joueur": "Défenseur cher", "Poste": "D", "Prix": 2_000_000, "Valeur marchée": 900_000,
                "Pts moy.": 4.0, "Pts moy. (saison)": 4.0, "Matchs (saison)": 8, "Matchs (équipe)": 24,
                "Team PtsAvg": 3.8, "MV 90 j": 880_000, "Décote (%)": -122.0,
                "Momentum 30 j (%)": -5.0, "Étranger": "", "Expire dans (s)": 36000, "AlphaScore": 30,
            },
        ])

    def test_engine_exposes_actionable_columns(self):
        result = dashboard.compute_recommendations_v2(self.market, self.roster)
        required = {
            "Décision", "Enchère max", "Valeur estimée", "Profit potentiel", "ROI potentiel (%)",
            "Remplace", "Gain pts/match", "Score équipe", "Score trading", "Confiance (%)", "Score décision"
        }
        self.assertTrue(required.issubset(result.columns))
        centre = result[result["Joueur"] == "Centre star"].iloc[0]
        self.assertEqual(centre["Remplace"], "Ailier faible")
        self.assertGreater(centre["Gain pts/match"], 3.0)
        self.assertGreater(centre["Valeur estimée"], centre["Prix"])
        self.assertLessEqual(centre["Enchère max"], centre["Valeur estimée"])

    def test_optimizer_respects_budget_and_unique_replacements(self):
        result = dashboard.compute_recommendations_v2(self.market, self.roster)
        plan, cost = dashboard.optimize_action_plan(result, budget=1_600_000, max_actions=5, foreign_capacity=6)
        self.assertLessEqual(cost, 1_600_000)
        self.assertLessEqual(len(plan), 5)
        replacements = [x for x in plan.get("Remplace", pd.Series(dtype=str)).tolist() if x != "Place libre"]
        self.assertEqual(len(replacements), len(set(replacements)))


    def test_position_normalization_accepts_missing_and_numeric_values(self):
        self.assertEqual(dashboard.pos_family_label(float("nan")), "?")
        self.assertEqual(dashboard.pos_family_label(12.0), "?")
        self.assertEqual(dashboard.pos_family_label(None), "?")
        self.assertEqual(dashboard.pos_family_label(" d "), "D")
        self.assertEqual(dashboard.pos_family_label("Gardien"), "G")
        self.assertEqual(dashboard.pos_family_label("Goalkeeper"), "G")
        self.assertEqual(dashboard.pos_family_label("Torhüter"), "G")
        self.assertEqual(dashboard.pos_family_label("Défenseur"), "D")
        self.assertEqual(dashboard.pos_family_label("Verteidiger"), "D")
        self.assertEqual(dashboard.pos_family_label("Centre"), "F")
        self.assertEqual(dashboard.pos_family_label("Ailier"), "F")
        self.assertEqual(dashboard.pos_family_label("Stürmer"), "F")

        roster = self.roster.copy()
        # Les réponses API réelles peuvent contenir plusieurs types dans cette colonne.
        roster["Poste"] = roster["Poste"].astype(object)
        roster.loc[0, "Poste"] = float("nan")
        roster.loc[1, "Poste"] = 12.0
        result = dashboard.compute_recommendations_v2(self.market, roster)
        self.assertFalse(result.empty)



    def test_goalie_never_replaces_a_defender(self):
        market = self.market.iloc[[0]].copy()
        market.loc[market.index[0], "Joueur"] = "Harri Säteri"
        market.loc[market.index[0], "Poste"] = "Gardien"
        result = dashboard.compute_recommendations_v2(market, self.roster)
        row = result.iloc[0]
        self.assertEqual(row["Famille poste"], "G")
        self.assertEqual(row["Remplace"], "Gardien faible")
        self.assertNotEqual(row["Remplace"], "Défenseur faible")

    def test_unknown_position_is_never_recommended(self):
        market = self.market.iloc[[0]].copy()
        market["Poste"] = pd.Series([float("nan")], index=market.index, dtype=object)
        result = dashboard.compute_recommendations_v2(market, self.roster)
        row = result.iloc[0]
        self.assertEqual(row["Famille poste"], "?")
        self.assertEqual(row["Remplace"], "Poste inconnu")
        self.assertEqual(row["Décision"], "ÉVITER")

    def test_competitive_bid_accounts_for_nine_managers(self):
        market = self.market.iloc[[0]].copy()
        market.loc[market.index[0], "Prix"] = 273_356
        market.loc[market.index[0], "Valeur marchée"] = 291_317
        market.loc[market.index[0], "MV 90 j"] = 291_317
        market.loc[market.index[0], "MV min 365 j"] = 285_000
        market.loc[market.index[0], "MV max 365 j"] = 300_000
        market.loc[market.index[0], "Offres (#)"] = 0
        result = dashboard.compute_recommendations_v2(market, self.roster)
        row = result.iloc[0]
        self.assertGreaterEqual(row["Offre conseillée"], 285_000)
        self.assertGreaterEqual(row["Plafond absolu"], row["Offre conseillée"])
        self.assertGreater(row["Offre conseillée"], row["Prix"])

    def test_roster_strategy_proposes_replacements_and_sale_prices(self):
        recommendations = dashboard.compute_recommendations_v2(self.market, self.roster)
        strategy = dashboard.compute_roster_strategy(self.roster, recommendations)
        required = {
            "Action", "Prix vente conseillé", "Remplaçant conseillé",
            "Offre remplaçant", "Gain remplacement", "Pourquoi"
        }
        self.assertTrue(required.issubset(strategy.columns))
        self.assertTrue(strategy["Action"].isin(["GARDER", "ÉCOUTER OFFRES", "VENDRE", "REMPLACER"]).all())


    def test_decision_colors_follow_v3_actions(self):
        expected = {
            "ACHETER": "decision-buy",
            "ACHETER / REVENDRE": "decision-trade",
            "ENCHÉRIR": "decision-bid",
            "ATTENDRE": "decision-wait",
            "ÉVITER": "decision-avoid",
            "REMPLACER": "decision-replace",
            "VENDRE": "decision-sell",
            "ÉCOUTER OFFRES": "decision-listen",
            "GARDER": "decision-keep",
        }
        for action, css_class in expected.items():
            key = "Décision" if action in {"ACHETER", "ACHETER / REVENDRE", "ENCHÉRIR", "ATTENDRE", "ÉVITER"} else "Action"
            self.assertEqual(dashboard._decision_row_class(pd.Series({key: action})), css_class)


if __name__ == "__main__":
    unittest.main()
