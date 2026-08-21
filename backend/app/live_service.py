# backend/app/live_service.py
import datetime as dt
import threading
import time
from typing import Any

import topscorers_dashboard as dashboard

_CACHE_TTL = 25
_cache_lock = threading.Lock()
_cache = {"expires": 0.0, "value": None}
_session = None

STAT_ALIASES = {
    "goals": ("goals", "goals_total", "goal"),
    "assists": ("assists", "assists_total", "assist"),
    "shots_on_goal": ("shots_on_goal", "shots_ongoal", "sog"),
    "blocked_shots": ("blocked_shots", "shots_blocked", "blocks"),
    "penalty_minutes": ("penalty_minutes", "pim", "penalties_minutes"),
    "plus_minus": ("plus_minus", "plusminus"),
    "faceoffs_won": ("faceoffs_won", "face_offs_won"),
    "faceoffs_lost": ("faceoffs_lost", "face_offs_lost"),
    "saves": ("saves", "goalie_saves"),
    "goals_against": ("goals_against", "ga"),
    "time_on_ice": ("time_on_ice", "toi", "minutes_played"),
}

OFFICIAL_SCORING = {
    "goal_goalie": 100, "goal_defender": 70, "goal_forward": 60,
    "assist_goalie": 55, "assist_defender": 50, "assist_forward": 40,
    "shutout": 40, "goal_shorthanded": 20, "hattrick": 20,
    "game_won": 15, "game_winning_goal": 15, "penalty_winning_goal": 15,
    "blocked_shot": 10, "assist_shorthanded": 10, "goal_powerplay": 10,
    "lineup": 5, "shot_on_goal": 5, "assist_powerplay": 5,
    "save": 4, "faceoff_won": 2, "time_on_ice": 1,
    "faceoff_lost": -2, "shot_missed": -5, "goal_against_team": -5,
    "penalty_2_minutes": -10, "goal_against": -15, "game_lost": -15,
    "foul_penalty_shot": -35, "penalty_10_minutes": -50,
    "game_misconduct": -50, "penalty_5_minutes": -75, "match_penalty": -125,
}


def _data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _pick(obj: Any, keys, default=None):
    if not isinstance(obj, dict):
        return default
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
        value = lowered.get(str(key).lower())
        if value is not None:
            return value
    for value in obj.values():
        if isinstance(value, dict):
            found = _pick(value, keys, None)
            if found is not None:
                return found
    return default


def _as_number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_list(obj: Any, keys):
    value = _pick(obj, keys, [])
    return value if isinstance(value, list) else []


def _request_json(session, path):
    response = session.get(f"{dashboard.BASE}{path}", timeout=15)
    if response.status_code in (401, 419):
        raise PermissionError("session_expired")
    if response.status_code in (402, 403):
        return {"member_required": True, "status_code": response.status_code}
    if response.status_code != 200:
        return None
    return response.json()


def _get_session():
    global _session
    if _session is None:
        _session = dashboard.login_session()
    return _session


def _active_player_ids(team_data):
    ids = set()
    for slot in _as_list(team_data, ("lineup",)):
        if not isinstance(slot, dict):
            continue
        current = slot.get("current")
        if isinstance(current, dict):
            current = current.get("id")
        if current is not None:
            ids.add(str(current))
    return ids


def _player_row(player, active_ids, stats_source=False):
    if not isinstance(player, dict):
        return None
    nested_player = player.get("player") if isinstance(player.get("player"), dict) else {}
    merged = {**nested_player, **player}
    pid = _pick(merged, ("id", "player_id"))
    first = str(_pick(merged, ("firstname", "first_name"), "") or "")
    last = str(_pick(merged, ("lastname", "last_name"), "") or "")
    name = str(_pick(merged, ("name", "player_name"), "") or "").strip() or f"{first} {last}".strip()
    team = _pick(merged, ("team",), {})
    if isinstance(team, dict):
        team = team.get("acronym") or team.get("name")
    live_stats = _pick(merged, ("live_stats", "statistics", "stats"), {})
    if not isinstance(live_stats, dict):
        live_stats = {}

    live_points = _as_number(_pick(merged, (
        "live_points", "points_live", "points_today", "gameday_points",
        "game_day_points", "round_points", "current_points",
    )))
    if live_points is None and stats_source:
        live_points = _as_number(merged.get("points"))

    stats = {}
    for label, aliases in STAT_ALIASES.items():
        stats[label] = _as_number(_pick(live_stats, aliases))
        if stats[label] is None:
            stats[label] = _as_number(_pick(merged, aliases))

    return {
        "id": pid,
        "name": name or f"Joueur {pid}",
        "position": _pick(merged, ("position_name", "position")),
        "team": team,
        "lined_up": str(pid) in active_ids if pid is not None else bool(_pick(merged, ("lined_up", "is_lined_up"), False)),
        "playing": bool(_pick(merged, ("is_playing", "playing", "live"), False)),
        "live_points": live_points,
        "season_points": _as_number(_pick(merged, ("season_points", "points"))),
        "stats": stats,
    }


def _normalize_games(payload):
    games = _as_list(_data(payload), ("games", "matches", "fixtures"))
    out = []
    for game in games:
        if not isinstance(game, dict):
            continue
        home = _pick(game, ("home_team", "home"))
        away = _pick(game, ("away_team", "away"))
        if isinstance(home, dict):
            home = home.get("acronym") or home.get("name")
        if isinstance(away, dict):
            away = away.get("acronym") or away.get("name")
        out.append({
            "home": home,
            "away": away,
            "home_score": _pick(game, ("home_score", "score_home")),
            "away_score": _pick(game, ("away_score", "score_away")),
            "status": _pick(game, ("status", "state", "game_status")),
            "starts_at": _pick(game, ("starts_at", "start_time", "date")),
            "live": bool(_pick(game, ("is_live", "live"), False)),
        })
    return out


def _fetch_uncached():
    global _session
    try:
        session = _get_session()
        team_payload = _request_json(session, f"/api/user/teams/{dashboard.TEAM_ID}")
        stats_payload = _request_json(session, f"/api/user/teams/{dashboard.TEAM_ID}/stats")
    except PermissionError:
        _session = None
        session = _get_session()
        team_payload = _request_json(session, f"/api/user/teams/{dashboard.TEAM_ID}")
        stats_payload = _request_json(session, f"/api/user/teams/{dashboard.TEAM_ID}/stats")

    team_data = _data(team_payload) if team_payload else {}
    stats_data = _data(stats_payload) if stats_payload else {}
    active_ids = _active_player_ids(team_data)

    stats_players = _as_list(stats_data, ("players", "lineup", "live_players", "player_stats"))
    team_players = _as_list(team_data, ("players",))
    source = stats_players or team_players
    players = [row for row in (_player_row(p, active_ids, bool(stats_players)) for p in source) if row]
    players.sort(key=lambda p: (not p["lined_up"], -(p["live_points"] or 0), p["name"]))

    games_payload = None
    for path in ("/api/games", "/api/games/live"):
        try:
            candidate = _request_json(session, path)
        except PermissionError:
            candidate = None
        if candidate:
            games_payload = candidate
            break
    games = _normalize_games(games_payload)

    total = _as_number(_pick(stats_data, (
        "live_points", "points_live", "points_today", "gameday_points",
        "game_day_points", "round_points", "total_points",
    )))
    known_points = [p["live_points"] for p in players if p["lined_up"] and p["live_points"] is not None]
    if total is None and known_points:
        total = sum(known_points)

    member_required = bool(
        isinstance(stats_payload, dict) and stats_payload.get("member_required")
    ) or bool(_pick(stats_data, ("member_required", "upgrade_required"), False))
    is_live = bool(_pick(stats_data, ("is_live", "live", "gameday_live"), False))
    is_live = is_live or any(g["live"] for g in games) or any(p["playing"] for p in players)

    if member_required:
        status, message = "MEMBER_REQUIRED", "L’accès aux points en direct nécessite TopScorers Member."
    elif is_live:
        status, message = "LIVE", "Matchs en cours — actualisation automatique toutes les 30 secondes."
    elif games or players:
        status, message = "READY", "Aucun match en direct actuellement. Dernières données disponibles affichées."
    else:
        status, message = "NO_DATA", "TopScorers ne fournit actuellement aucune donnée live exploitable."

    return {
        "ok": True,
        "status": status,
        "message": message,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "team": "Droken",
        "team_id": dashboard.TEAM_ID,
        "live_points": total,
        "rank": _pick(stats_data, ("live_rank", "rank", "position")),
        "players": players,
        "games": games,
        "member_required": member_required,
        "cache_seconds": _CACHE_TTL,
        "official_scoring": OFFICIAL_SCORING,
    }


def get_live_snapshot():
    now = time.monotonic()
    with _cache_lock:
        if _cache["value"] is not None and now < _cache["expires"]:
            return {**_cache["value"], "cached": True}
        try:
            value = _fetch_uncached()
            _cache.update(value=value, expires=now + _CACHE_TTL)
            return {**value, "cached": False}
        except Exception as exc:
            if _cache["value"] is not None:
                return {
                    **_cache["value"],
                    "cached": True,
                    "stale": True,
                    "message": f"Dernières données connues — TopScorers temporairement indisponible ({exc}).",
                }
            return {
                "ok": False,
                "status": "ERROR",
                "message": f"Live temporairement indisponible: {exc}",
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "players": [],
                "games": [],
                "official_scoring": OFFICIAL_SCORING,
            }
