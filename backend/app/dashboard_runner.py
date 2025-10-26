# backend/app/dashboard_runner.py
import os
import importlib
import traceback
from pathlib import Path

OUTPUT_PATH = Path(os.getenv("DASHBOARD_HTML", "/data/dashboard_topscorers.html")).resolve()

def generate_dashboard() -> str:
    try:
        mod = importlib.import_module("topscorers_dashboard")
        # force la cible de sortie dans le module si elle existe
        if hasattr(mod, "OUTPUT_HTML"):
            mod.OUTPUT_HTML = str(OUTPUT_PATH)
        if not hasattr(mod, "main"):
            raise RuntimeError("topscorers_dashboard.main() introuvable")
        mod.main()
    except Exception as e:
        raise RuntimeError(f"Echec génération: {e}\n{traceback.format_exc()}")

    if not OUTPUT_PATH.exists():
        raise RuntimeError(f"Dashboard attendu non trouvé: {OUTPUT_PATH}")
    return str(OUTPUT_PATH)
