# topscorers_dashboard.py
import os, sys, time, json, itertools
import datetime as dt
from urllib.parse import unquote

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
pd.set_option("future.no_silent_downcasting", True)

# ----------------- CONFIG -----------------
BASE = "https://topscorers.ch"
EMAIL          = os.getenv("TOPS_EMAIL")
PASSWORD       = os.getenv("TOPS_PASSWORD")
LEAGUE_ID      = os.getenv("TOPS_LEAGUE_ID", "92556")
TEAM_ID        = (os.getenv("TOPS_TEAM_ID") or "506387").strip()
TEAM_QUERY     = (os.getenv("TOPS_TEAM_QUERY") or "").strip()
RECO_BUDGET    = int(os.getenv("RECO_BUDGET", "10000000"))
OUTPUT_HTML    = os.getenv("DASHBOARD_HTML", "dashboard_topscorers.html")
RECO_HISTORY_CSV = os.getenv("RECOMMENDATION_HISTORY_CSV", "/data/recommendation_history.csv")
RECO_MAX_ACTIONS = int(os.getenv("RECO_MAX_ACTIONS", "5"))
RECO_MIN_MARGIN = float(os.getenv("RECO_MIN_MARGIN", "0.10"))
RECO_MODE = (os.getenv("RECO_MODE", "balanced") or "balanced").strip().lower()
LEAGUE_MANAGERS = max(2, int(os.getenv("LEAGUE_MANAGERS", "9")))
BID_INCREMENT = max(1, int(os.getenv("BID_INCREMENT", "1000")))

# Poids AlphaScore
ALPHA_W_VALUE   = float(os.getenv("ALPHA_W_VALUE",  "0.30"))
ALPHA_W_EFF     = float(os.getenv("ALPHA_W_EFF",    "0.20"))
ALPHA_W_FORM    = float(os.getenv("ALPHA_W_FORM",   "0.20"))
ALPHA_W_CONSIST = float(os.getenv("ALPHA_W_CONSIST","0.10"))
ALPHA_W_USAGE   = float(os.getenv("ALPHA_W_USAGE",  "0.10"))
ALPHA_W_CTX     = float(os.getenv("ALPHA_W_CTX",    "0.07"))
ALPHA_W_MARKET  = float(os.getenv("ALPHA_W_MARKET", "0.03"))

# Forme multi-saisons
FORM_W_CUR = float(os.getenv("FORM_W_CUR", "0.6"))
FORM_W_N1  = float(os.getenv("FORM_W_N1",  "0.3"))
FORM_W_N2  = float(os.getenv("FORM_W_N2",  "0.1"))

# Ajustements
FOREIGNER_PENALTY = float(os.getenv("FOREIGNER_PENALTY", "0.03"))
OFFERS_PENALTY    = float(os.getenv("OFFERS_PENALTY",    "0.02"))
EXPIRY_BOOST_HRS  = float(os.getenv("EXPIRY_BOOST_HOURS","6"))

MUST_BUY_THRESHOLD_FALLBACK = float(os.getenv("MUST_BUY_THRESHOLD", "85"))

# Historique valeurs
ADD_PRICE_FEATURES  = os.getenv("ADD_PRICE_FEATURES", "1").strip().lower() in ("1","true","yes","on")
PRICE_WINDOW_DAYS   = int(os.getenv("PRICE_WINDOW_DAYS", "180"))
PRICE_MOMENTUM_DAYS = int(os.getenv("PRICE_MOMENTUM_DAYS", "30"))

# Équipes pour "Tous les joueurs"
DEFAULT_TEAMS = [103144,101152,102126,101150,101149,102127,102128,101139,101144,103138,103140,103141,101060,101151]
ALL_PLAYERS_TEAMS_ENV     = os.getenv("ALL_PLAYERS_TEAMS", "").strip()
ALL_PLAYERS_FETCH_DETAILS = os.getenv("ALL_PLAYERS_FETCH_DETAILS", "1").strip().lower() in ("1","true","yes","on")

# Équipes des autres managers
OTHER_TEAM_IDS_ENV   = os.getenv("OTHER_TEAM_IDS", "").strip()
OTHER_TEAM_NAMES_ENV = os.getenv("OTHER_TEAM_NAMES", "").strip()
SHOW_ME_AS_USERNAME  = os.getenv("SHOW_ME_AS_USERNAME", "1").strip().lower() in ("1","true","yes","on")

TEAM_LOGO_URL  = os.getenv("TEAM_LOGO_URL","https://assets.topscorers.ch/img/cache/t672/logos/103141.png")

HEADERS_COMMON = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Language": "fr",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "User-Agent": "Mozilla/5.0",
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "x-app-version": "1.5.5",
}
TEAM_USERNAME_CACHE = {}

# ----------------- THEME + HTML -----------------
BOOTSTRAP_CSS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
BOOTSTRAP_JS  = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"

def build_html_page(sections, must_buy_threshold: float):
    tabs, panes = [], []
    for i, sec in enumerate(sections):
        active   = "active" if i == 0 else ""
        selected = "true" if i == 0 else "false"
        tabs.append(f"""
<li class="nav-item" role="presentation">
  <button class="nav-link {active}" id="{sec['id']}-tab" data-bs-toggle="tab"
          data-bs-target="#{sec['id']}" type="button" role="tab"
          aria-controls="{sec['id']}" aria-selected="{selected}">
    {sec['title']}
  </button>
</li>""")
        panes.append(f"""
<div class="tab-pane fade show {active}" id="{sec['id']}" role="tabpanel" aria-labelledby="{sec['id']}-tab">
  <div class="pt-3">{sec['content']}</div>
  {sec.get('script','')}
</div>""")

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TopScorers — Dashboard</title>
<link href="{BOOTSTRAP_CSS}" rel="stylesheet">
<style>
  :root {{
    --lhc-red:#C8102E;
    --lhc-green:#19C37D;
    --lhc-bg:#0E1116;
    --lhc-card:#171A22;
    --lhc-text:#FFFFFF;
    --lhc-black:#000000;
    --lhc-muted:#C7CED9;
    --row-border:#2B3140;

    --bs-body-bg: var(--lhc-bg);
    --bs-body-color: var(--lhc-text);
    --bs-border-color: var(--row-border);
    --bs-link-color: var(--lhc-red);
    --bs-secondary-color: var(--lhc-muted);
    --bs-nav-tabs-border-color: var(--row-border);
    --bs-nav-tabs-link-hover-border-color: var(--row-border) var(--row-border) transparent;
    --bs-nav-tabs-link-active-bg: var(--lhc-red);
    --bs-nav-tabs-link-active-color: #fff;
    --bs-nav-tabs-link-active-border-color: var(--lhc-red) var(--lhc-red) var(--lhc-card);
  }}

  body {{ background:var(--lhc-bg); color:var(--lhc-text); }}
  .text-secondary {{ color:var(--lhc-muted) !important; }}
  .brand {{ display:flex; align-items:center; gap:.75rem; }}
  .brand-logo {{
    height:44px; width:44px; border-radius:10px; background:#fff;
    padding:4px; object-fit:contain;
    box-shadow: 0 0 0 1px rgba(0,0,0,.4), 0 1px 6px rgba(0,0,0,.35);
  }}
  .brand-title {{ color:var(--lhc-red); font-weight:600; }}
  .nav-tabs .nav-link {{ color:var(--lhc-muted); }}
  .nav-tabs .nav-link.active {{ color:#fff; background:var(--lhc-red); border-color:var(--lhc-red); }}

  .card {{ background:var(--lhc-card); border:1px solid var(--row-border); border-radius:14px; }}
  .table {{ color:var(--lhc-text); border-color:var(--row-border); }}
  table.table-sm td, table.table-sm th {{ padding:.42rem .6rem; vertical-align: middle; }}
  .table-wrapper {{ overflow-x:auto; }}

  .table td, .table th {{ color: var(--lhc-text) !important; }}
  .table th {{ font-weight: 600; color: var(--lhc-muted) !important; }}

  table a.pm-open {{ color: var(--lhc-text); text-decoration: none; font-weight: 500; }}
  table a.pm-open:hover {{ color: var(--lhc-red); text-decoration: underline; }}

  .table .score-mustbuy td {{
    background-color: #baf7d6 !important;
    color: var(--lhc-black) !important;
    font-weight: 600;
    text-shadow: none;
  }}
  .table .score-mustbuy a.pm-open {{ color: var(--lhc-black) !important; text-decoration: underline; }}

  input.form-control-sm, select.form-select-sm {{
    background:#10141C; color:var(--lhc-text); border:1px solid var(--row-border);
  }}
  input.form-control-sm:focus, select.form-select-sm:focus {{
    background:#0C1016; border-color:var(--lhc-red);
    box-shadow: 0 0 0 .15rem rgba(200,16,46,.15);
  }}

  th.sort-asc::after  {{ content:" \\25B2"; font-size:.7em; color:var(--lhc-muted); }}
  th.sort-desc::after {{ content:" \\25BC"; font-size:.7em; color:var(--lhc-muted); }}
  th.sort-asc, th.sort-desc {{ color:#fff; }}

  .badge-chip {{ display:inline-block; padding:.15rem .45rem; border-radius:.5rem; font-size:.75rem; border:1px solid #d0d5dd; white-space:nowrap; }}
  .chip-owner   {{ background:#ffffff; color:#000; border-color:#d0d5dd; }}
  .chip-foreign {{ background:#ffe3e7; color:#000; border-color:#ff9aa9; }}

  .modal-content {{ background:var(--lhc-card); color:var(--lhc-text); border:1px solid var(--row-border); border-radius:16px; }}
  .modal-header, .modal-footer {{ border-color:var(--row-border); }}
  .pm-head {{ display:flex; align-items:center; gap:14px; }}
  .pm-avatar {{
    width:46px; height:46px; border-radius:50%; background:#0f1320;
    display:flex; align-items:center; justify-content:center; font-weight:700; letter-spacing:.3px;
    border:1px solid var(--row-border);
  }}
  .pm-badges .badge {{ background:#10141C; border:1px solid var(--row-border); color:var(--lhc-muted); }}
  .statcard {{
    border:1px solid var(--row-border); border-radius:12px; padding:.75rem;
    background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0));
  }}
  .statcard .label {{ font-size:.8rem; color:var(--lhc-muted); }}
  .statcard .value {{ font-size:1.05rem; font-weight:600; }}
  .btn-soft {{ border:1px solid var(--row-border); color:#fff; }}
  .btn-soft:hover {{ border-color:#3a4154; background:#0f1320; }}
</style>
</head>
<body class="p-3 p-md-4">
<noscript><div class="alert alert-warning" role="alert" style="max-width:900px">
  JavaScript désactivé : les <b>tableaux</b> s’affichent, le filtrage, le tri, la pagination et les pop-ups ne fonctionneront pas.
</div></noscript>

<div class="container-fluid">
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <div class="brand">
      <img src="{TEAM_LOGO_URL}" class="brand-logo" alt="Logo équipe">
      <h1 class="h3 m-0 brand-title">TopScorers — Dashboard</h1>
    </div>
    <span class="badge rounded-pill" style="background:#10141C; border:1px solid var(--row-border);">{now}</span>
  </div>

  <ul class="nav nav-tabs" id="tabs" role="tablist">{''.join(tabs)}</ul>
  <div class="tab-content" id="tabsContent">{''.join(panes)}</div>
</div>

<!-- MODAL JOUEUR -->
<div class="modal fade" id="playerModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header">
        <div class="pm-head">
          <div class="pm-avatar" id="pmAvatar">⚑</div>
          <div>
            <div class="pm-title h5 m-0" id="pmName">Joueur</div>
            <div class="pm-badges small">
              <span class="badge" id="pmTeamBadge">—</span>
              <span class="badge" id="pmPosBadge">—</span>
            </div>
          </div>
        </div>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Fermer"></button>
      </div>

      <div class="modal-body">
        <div class="row g-3">
          <div class="col-lg-7">
            <div class="statcard">
              <div class="label mb-1">Historique de valeur</div>
              <div id="pmSpark" style="min-height:44px">—</div>
              <div id="pmDetails" class="small mt-2 text-secondary">—</div>
            </div>
          </div>
          <div class="col-lg-5">
            <div class="row g-2">
              <div class="col-6">
                <div class="statcard text-center">
                  <div class="label">Pts moy.</div>
                  <div class="value" id="pmPts">—</div>
                </div>
              </div>
              <div class="col-6">
                <div class="statcard text-center">
                  <div class="label">AlphaScore</div>
                  <div class="value" id="pmAlpha">—</div>
                </div>
              </div>
              <div class="col-12">
                <div class="statcard">
                  <div class="label">Valeur / Prix</div>
                  <div class="value" id="pmVal">—</div>
                </div>
              </div>
            </div>
          </div>
        </div>        
      </div>

      <div class="modal-footer">
        <button class="btn btn-soft btn-sm" data-bs-dismiss="modal">Fermer</button>
      </div>
    </div>
  </div>
</div>

<script src="{BOOTSTRAP_JS}"></script>
<script>
document.addEventListener('DOMContentLoaded', function () {{

  /* ===========================
     UTILITAIRES
  =========================== */

  function colIndexByName(table, namePartLower) {{
    namePartLower = (namePartLower||'').toLowerCase();
    if (!table || !table.tHead || !table.tHead.rows.length) return -1;
    var ths = table.tHead.rows[0].cells;
    for (var i=0;i<ths.length;i++) {{
      var t = (ths[i].innerText||'').trim().toLowerCase();
      if (t.indexOf(namePartLower) >= 0) return i;
    }}
    return -1;
  }}

  function initials(name) {{
    if (!name) return '⚑';
    var parts = name.trim().split(/\\s+/);
    if (!parts.length) return '⚑';
    var a = parts[0] ? parts[0].charAt(0) : '';
    var b = parts.length>1 ? parts[parts.length-1].charAt(0) : '';
    var up = (a+b).toUpperCase();
    return up || '⚑';
  }}

  /* ===========================
     MASTER ROWS + FLAGS
     - qtext  : filtre texte (quickfilter)
     - qowner : filtre propriétaire / équipe
     - qmatch : AND des deux
  =========================== */

  function cellText(row, idx) {{
    return (row.cells[idx] ? row.cells[idx].innerText : '').trim();
  }}

  /* ===========================
     FILTRE / TRI / PAGER (V2)
  =========================== */

  function attachQuickFilter(input, table) {{
    captureAllRows(table);
    if (!table._allRowsMaster) return;

    input.addEventListener('input', function () {{
      var q = (this.value || '').toLowerCase();
      table._allRowsMaster.forEach(function (r) {{
        var txt = (r._allTextCache || (r._allTextCache = r.innerText.toLowerCase()));
        r.dataset.qtext = (q === '' || txt.indexOf(q) !== -1) ? '1' : '0';
      }});
      recomputeEligibility(table);
      if (table._pager) {{ table._pager.page = 1; table._pager.rebuild(); }}
    }});
  }}

  function enableTableSortV2(table) {{
    captureAllRows(table);
    if (!table || !table.tHead || !table.tBodies || !table.tBodies[0]) return;
    var ths = table.tHead.rows[0].cells;

    Array.prototype.forEach.call(ths, function (th, idx) {{
      th.style.cursor = 'pointer';
      th.addEventListener('click', function () {{
        var isAsc = !th.classList.contains('sort-asc');

        Array.prototype.forEach.call(ths, function (other) {{
          if (other !== th) other.classList.remove('sort-asc', 'sort-desc');
        }});
        th.classList.toggle('sort-asc', isAsc);
        th.classList.toggle('sort-desc', !isAsc);

        var collator = new Intl.Collator(undefined, {{ numeric: true, sensitivity: 'base' }});
        table._allRows = table._allRowsMaster.slice().sort(function (a, b) {{
          var aText = cellText(a, idx), bText = cellText(b, idx);
          return isAsc ? collator.compare(aText, bText) : collator.compare(bText, aText);
        }});

        if (table._pager) {{ table._pager.page = 1; table._pager.rebuild(); }}
      }});
    }});
  }}

  function enablePagerV2(table, pageSize) {{
    if (!table || !table.tBodies || !table.tBodies[0]) return;
    var tbody = table.tBodies[0];
    captureAllRows(table);
    if (!table._allRowsMaster) return;

    function eligible() {{
      var src = (table._allRows || table._allRowsMaster);
      return src.filter(function (r) {{ return r.dataset && r.dataset.qmatch !== '0'; }});
    }}

    var pager = {{
      page: 1,
      size: pageSize || 25,
      rebuild: function () {{
        var elig = eligible();
        var total = elig.length;
        var pages = Math.max(1, Math.ceil(total / pager.size));
        if (pager.page > pages) pager.page = pages;

        var start = (pager.page - 1) * pager.size;
        var end = start + pager.size;
        var slice = elig.slice(start, end);

        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        slice.forEach(function (r) {{
          r.style.display = '';
          tbody.appendChild(r);
          // Enhancement systématique et idempotent
          enhanceRowPlayerCell(table, r);
        }});

        // Pager UI
        if (!table._pagerEl) {{
          table._pagerEl = document.createElement('div');
          table._pagerEl.className = 'd-flex justify-content-between align-items-center mt-2';
          table.parentNode.appendChild(table._pagerEl);
        }}
        var info = 'Page ' + pager.page + ' / ' + pages + ' — ' + total + ' lignes';
        var btnPrev = '<button class="btn btn-sm btn-outline-light me-2" data-act="prev" type="button">&laquo;</button>';
        var btnNext = '<button class="btn btn-sm btn-outline-light ms-2" data-act="next" type="button">&raquo;</button>';
        table._pagerEl.innerHTML = '<div class="small text-secondary">' + info + '</div><div>' + btnPrev + btnNext + '</div>';
        table._pagerEl.querySelector('[data-act="prev"]').onclick = function (ev) {{
          ev.preventDefault();
          if (pager.page > 1) {{ pager.page--; pager.rebuild(); }}
        }};
        table._pagerEl.querySelector('[data-act="next"]').onclick = function (ev) {{
          ev.preventDefault();
          if (pager.page < pages) {{ pager.page++; pager.rebuild(); }}
        }};

        // S'assure qu'un seul écouteur modal gère tous les liens (toutes pages)
        attachModalDelegate(table);
      }}
  }};

    table._pager = pager;
    pager.rebuild();
  }}

  /* ===========================
     COLONNES AVANCÉES
  =========================== */
  function enableColumnToggles(table) {{
    if (!table || !table.tHead) return;
    var ths = table.tHead.rows[0].cells;
    var advCols = [];
    var advNames = ['mv 90','mv min','mv max','momentum 30','décote vs max','mv spark','team ptsavg','pts / 100k'];

    Array.prototype.forEach.call(ths, function(th, idx){{
      var name = (th.innerText||'').toLowerCase();
      for (var i=0;i<advNames.length;i++) {{
        if (name.indexOf(advNames[i]) >= 0) advCols.push(idx);
      }}
    }});
    if (!advCols.length) return;

    var wrapper = table.closest('.card');
    if (!wrapper) return;

    var bar = document.createElement('div');
    bar.className = 'd-flex justify-content-end mb-2';
    var btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-outline-light';
    btn.textContent = 'Colonnes avancées';
    btn.setAttribute('aria-pressed','false');
    var visible = false;

    btn.onclick = function(){{
      visible = !visible;
      btn.setAttribute('aria-pressed', visible ? 'true' : 'false');
      toggleCols(visible);
      if (table._pager) table._pager.rebuild();
    }};
    bar.appendChild(btn);
    wrapper.insertBefore(bar, wrapper.firstChild);

    function toggleCols(show) {{
      var display = show ? '' : 'none';
      Array.prototype.forEach.call(ths, function(th, i){{
        if (advCols.indexOf(i) >= 0) th.style.display = display;
      }});
      if (table.tBodies && table.tBodies[0]) {{
        Array.prototype.forEach.call(table.tBodies[0].rows, function(r){{
          Array.prototype.forEach.call(r.cells, function(td, i){{
            if (advCols.indexOf(i) >= 0) td.style.display = display;
          }});
        }});
      }}
    }}
    toggleCols(false);
  }}

  /* ===========================
     MUST-BUY (seuil dynamique)
  =========================== */
  function findScoreColIndex(tbl) {{
    if (tbl.tHead && tbl.tHead.rows.length) {{
      var headCells = tbl.tHead.rows[0].cells;
      for (var i=0;i<headCells.length;i++) {{
        var name = (headCells[i].innerText||'').trim().toLowerCase();
        if (name === 'alphascore' || name.indexOf('alpha') >= 0) return i;
      }}
    }}
    var rows = (tbl.tBodies && tbl.tBodies[0]) ? Array.prototype.slice.call(tbl.tBodies[0].rows) : [];
    if (rows.length) {{
      var lastIdx = rows[0].cells.length - 1;
      for (var j=lastIdx; j>=0; j--) {{
        var hits=0, trials=0;
        for (var k=0; k<Math.min(5, rows.length); k++) {{
          var r = rows[k];
          var txt = (r.cells[j] ? r.cells[j].innerText : '').trim().replace(',', '.');
          var v = parseFloat(txt);
          if (!isNaN(v)) hits++;
          trials++;
        }}
        if (trials>0 && hits >= Math.ceil(trials*0.6)) return j;
      }}
    }}
    return -1;
  }}

  var mustBuyThreshold = {must_buy_threshold:.2f};

  function colorizeMustBuy(tblId) {{
    var tbl = document.getElementById(tblId);
    if (!tbl) return;
    function apply() {{
      if (!tbl || !tbl.tBodies || !tbl.tBodies[0]) return;
      var scoreIdx = findScoreColIndex(tbl);
      if (scoreIdx < 0) return;
      Array.prototype.slice.call(tbl.tBodies[0].rows).forEach(function(row){{
        row.classList.remove('score-mustbuy');
        var cell = row.cells[scoreIdx];
        if (!cell) return;
        var v = parseFloat((cell.innerText||'').replace(',', '.'));
        if (!isNaN(v) && v >= mustBuyThreshold) row.classList.add('score-mustbuy');
      }});
    }}
    if (tbl._pager) {{
      var oldRebuild = tbl._pager.rebuild;
      tbl._pager.rebuild = function() {{
        oldRebuild.call(tbl._pager);
        apply();
      }};
      tbl._pager.rebuild();
    }} else {{
      setTimeout(apply, 50);
    }}
  }}

  /* ===========================
     MODAL JOUEUR
  =========================== */
  var modalEl = document.getElementById('playerModal');
  var bsModal = modalEl ? new bootstrap.Modal(modalEl) : null;

  function openPlayerModalFromRow(tbl, row) {{
    if (!bsModal) return;

    function getIdx(name) {{ return colIndexByName(tbl, (name||'').toLowerCase()); }}
    function getTxt(name) {{
      var idx = getIdx(name); if (idx < 0) return '';
      return (row.cells[idx] ? row.cells[idx].innerText : '').trim();
    }}
    function getHTML(name) {{
      var idx = getIdx(name); if (idx < 0) return '';
      return (row.cells[idx] ? row.cells[idx].innerHTML : '').trim();
    }}

    var name  = getTxt('joueur') || '—';
    var team  = getTxt('équipe');
    var pos   = getTxt('poste') || '—';
    var pts   = getTxt('pts moy.') || getTxt('pts moy. (saison)') || '—';
    var val   = getTxt('valeur marchée') || getTxt('valeur') || '—';
    var prix  = getTxt('prix');
    var alpha = getTxt('alphascore') || '—';
    var spark = getHTML('mv spark');

    modalEl.querySelector('#pmAvatar').textContent = initials(name);
    modalEl.querySelector('#pmName').textContent   = name;
    modalEl.querySelector('#pmTeamBadge').textContent = team ? team : '—';
    modalEl.querySelector('#pmPosBadge').textContent  = pos;

    modalEl.querySelector('#pmPts').textContent   = pts;
    modalEl.querySelector('#pmVal').textContent   = prix ? (val + ' / ' + prix) : val;
    modalEl.querySelector('#pmAlpha').textContent = alpha;

    var sparkEl = modalEl.querySelector('#pmSpark');
    sparkEl.innerHTML = spark || '<span class="text-secondary">Aucune donnée</span>';

    var mv90   = getTxt('mv 90 j');
    var mvmin  = getTxt('mv min 365 j');
    var mvmax  = getTxt('mv max 365 j');
    var mom30  = getTxt('momentum 30 j');
    var discMx = getTxt('décote vs max 365');
    var details = [];
    if (mv90)  details.push('<b>MV 90 j</b> : ' + mv90);
    if (mvmin) details.push('<b>Min 365 j</b> : ' + mvmin);
    if (mvmax) details.push('<b>Max 365 j</b> : ' + mvmax);
    if (mom30) details.push('<b>Momentum 30 j</b> : ' + mom30);
    if (discMx)details.push('<b>Décote vs max 365</b> : ' + discMx);
    modalEl.querySelector('#pmDetails').innerHTML = details.length ? details.join(' · ') : "<span class='text-secondary'>—</span>";

    bsModal.show();
  }}

  function attachModalDelegate(table) {{
    if (!table || table._pmDelegateAttached) return;
    table.addEventListener('click', function (e) {{
      var a = e.target.closest('a.pm-open');
      if (!a) return;
      e.preventDefault();
      var row = a.closest('tr');
      if (row) openPlayerModalFromRow(table, row);
    }});
    table._pmDelegateAttached = true;
  }}

  function enhanceRowPlayerCell(table, row) {{
    var idxJ = colIndexByName(table, 'joueur'); if (idxJ < 0) return;
    var cell = row.cells[idxJ]; if (!cell) return;

    // si déjà un lien .pm-open, ne rien faire
    if (cell.querySelector('a.pm-open')) return;

    var name = (cell.innerText || '').trim();
    if (!name) return;

    cell.textContent = '';
    var link = document.createElement('a');
    link.href = '#';
    link.className = 'pm-open';
    link.textContent = name;
    cell.appendChild(link);
  }}

  function enhancePlayerCells(table) {{
    if (!table || !table.tBodies || !table.tBodies[0]) return;
    Array.prototype.slice.call(table.tBodies[0].rows).forEach(function(row){{
      enhanceRowPlayerCell(table, row);
    }});
  }}
  window.enhanceRowPlayerCell = enhanceRowPlayerCell;
  window.attachModalDelegate  = attachModalDelegate;
  /* ===========================
     INIT (toutes les tables)
  =========================== */
  document.querySelectorAll('table').forEach(function (tbl) {{
    captureAllRows(tbl);
    enableTableSortV2(tbl);
    enablePagerV2(tbl, 25);
    enableColumnToggles(tbl);
    enhancePlayerCells(tbl); // liens pour la page courante
    attachModalDelegate(tbl);

  }});

  // Quickfilters
  document.querySelectorAll('[data-quickfilter-table]').forEach(function(input){{
    var tableId = input.getAttribute('data-quickfilter-table');
    var tbl = document.getElementById(tableId);
    if (tbl) attachQuickFilter(input, tbl);
  }});

  // Colorisation must-buy
  ['tblVentes','tblRecos','tblAllPlayers','tblOwners','tblTradePlan','tblByPos','tblUnder','tblOver']
    .forEach(colorizeMustBuy);

}});

// ====== OUTILS GLOBALS pour l’onglet "Équipe" (stats cross-pages) ======
function captureAllRows(table) {{
    if (!table || !table.tBodies || !table.tBodies[0]) return;
    if (!table._allRowsMaster) {{
      table._allRowsMaster = Array.prototype.slice.call(table.tBodies[0].rows);
      table._allRowsMaster.forEach(function (r) {{
        if (!r.dataset) r.dataset = {{}};
        if (!('qtext' in r.dataset))  r.dataset.qtext  = '1';
        if (!('qowner' in r.dataset)) r.dataset.qowner = '1';
        r.dataset.qmatch = (r.dataset.qtext !== '0' && r.dataset.qowner !== '0') ? '1' : '0';
      }});
    }}
    if (!table._allRows) {{
      table._allRows = table._allRowsMaster.slice();
    }}
  }}

function recomputeEligibility(tbl) {{
  if (!tbl || !tbl._allRowsMaster) return;

  (tbl._allRowsMaster || []).forEach(function (row) {{
    var qtextOk  = (row.dataset && row.dataset.qtext  !== '0');   // filtre texte
    var qownerOk = (row.dataset && row.dataset.qowner !== '0');   // filtre propriétaire/équipe
    row.dataset.qmatch = (qtextOk && qownerOk) ? '1' : '0';       // état combiné
}});
}}


function norm(x) {{
  return (x == null ? '' : String(x)).trim().replace(/\\s+/g, ' ');
}}

function eligibleRowsFromMaster(tbl) {{
  var src = (tbl._allRows || tbl._allRowsMaster || []);
  return src.filter(function (r) {{ return r.dataset && r.dataset.qmatch !== '0'; }});
}}

function getCellText(row, idx) {{
  return (idx >= 0 && row.cells[idx] ? row.cells[idx].innerText : '').trim();
}}
function parseNum(x) {{
  var s = (x||'').toString().replace(/\\s/g,'').replace(',', '.');
  var v = parseFloat(s);
  return isNaN(v) ? null : v;
}}
function famPoste(s) {{
  s = (s||'').toUpperCase();
  if (s.indexOf('G')===0) return 'G';
  if (s.indexOf('D')===0) return 'D';
  if (s.indexOf('C')===0) return 'C';
  if (s.indexOf('W')>=0 || s.indexOf('AIL')>=0) return 'W';
  return 'W';
}}

function applyOwnerTeamFilters(ownerSelId, teamSelId, tableId, summaryId, top5Id) {{
  var ownerSel = document.getElementById(ownerSelId);
  var teamSel  = document.getElementById(teamSelId);
  var tbl      = document.getElementById(tableId);
  var summary  = document.getElementById(summaryId);
  var top5Div  = document.getElementById(top5Id);
  if (!ownerSel || !teamSel || !tbl || !tbl.tBodies || !tbl.tBodies[0]) return;

  function colIndex(namePart) {{
    if (tbl.tHead && tbl.tHead.rows.length) {{
      var ths = tbl.tHead.rows[0].cells;
      for (var i=0;i<ths.length;i++) {{
        var t = (ths[i].innerText || '').trim().toLowerCase();
        if (t.indexOf(namePart.toLowerCase()) >= 0) return i;
      }}
    }}
    return -1;
  }}
  var idxOwner   = colIndex('propriétaire');
  var idxPoste   = colIndex('poste');
  var idxTeam    = colIndex('équipe');
  var idxValeur  = colIndex('valeur');
  var idxPtsMoy  = colIndex('pts moy');
  var idxPts100k = colIndex('pts / 100k');
  var idxAlpha   = colIndex('alphascore');
  var idxEtr     = colIndex('étranger');
  var idxJoueur  = colIndex('joueur');

  function recalc() {{
      var ownerVal = norm(ownerSel.value);
      var teamVal  = norm(teamSel.value);

      captureAllRows(tbl);
      (tbl._allRowsMaster || []).forEach(function (r) {{
        var ownerTxt = norm(getCellText(r, idxOwner));
        var teamTxt  = norm(getCellText(r, idxTeam));

        var ownerOk = (ownerVal === '__ALL__' || ownerTxt === ownerVal);
        var teamOk  = (teamVal  === '__ALL__' || teamTxt  === teamVal);

        if (!r.dataset) r.dataset = {{}};
        r.dataset.qowner = (ownerOk && teamOk) ? '1' : '0';
      }});

      recomputeEligibility(tbl);

      // Rebuild pager et réapplique les liens modals sur la page courante
    if (tbl._pager) {{ tbl._pager.page = 1; tbl._pager.rebuild(); }}

// (Si pas de pager, on s'assure quand même que les liens existent)
var _rows = (tbl && tbl.tBodies && tbl.tBodies[0]) ? tbl.tBodies[0].rows : null;
if (_rows && _rows.length && window.enhanceRowPlayerCell) {{
  for (var i = 0; i < _rows.length; i++) {{
    window.enhanceRowPlayerCell(tbl, _rows[i]);
  }}
}}

// S'assure qu'un seul écouteur modal gère tous les liens (toutes pages)
if (window.attachModalDelegate) {{ window.attachModalDelegate(tbl); }}

      // ---------- Stats + Top 5 sur les lignes visibles ----------
      var visible = (tbl._allRows || tbl._allRowsMaster || []).filter(function (r) {{
        return r.dataset && r.dataset.qmatch !== '0';
      }});

      if (!visible.length) {{
        summary.innerHTML = "<div class='col-12 text-secondary'>Aucun joueur avec cette combinaison de filtres.</div>";
        top5Div.innerHTML = "<span class='text-secondary'>—</span>";
        return;
      }}

      var n = 0, sumValeur=0, sumPtsMoy=0, sumPts100k=0, sumAlpha=0, nbEtr=0;
      var c=0,w=0,d=0,g=0;
      var players = [];

      visible.forEach(function (r) {{
        var vValeur  = parseNum(getCellText(r, idxValeur));
        var vPtsMoy  = parseNum(getCellText(r, idxPtsMoy));
        var vPts100k = parseNum(getCellText(r, idxPts100k));
        var vAlpha   = parseNum(getCellText(r, idxAlpha));
        var vPoste   = getCellText(r, idxPoste);
        var vEtrTxt  = getCellText(r, idxEtr);
        var vJoueur  = getCellText(r, idxJoueur);
        var vTeam    = getCellText(r, idxTeam);

        n += 1;
        if (vValeur!=null)  sumValeur += vValeur;
        if (vPtsMoy!=null)  sumPtsMoy += vPtsMoy;
        if (vPts100k!=null) sumPts100k += vPts100k;
        if (vAlpha!=null)   sumAlpha += vAlpha;

        var fam = famPoste(vPoste);
        if (fam==='C') c++; else if (fam==='W') w++; else if (fam==='D') d++; else if (fam==='G') g++;

        if ((vEtrTxt || '').toLowerCase().indexOf('étranger')>=0) nbEtr++;

        players.push({{ joueur:vJoueur, poste:vPoste, equipe:vTeam, valeur:vValeur, ptsm:vPtsMoy, alpha:vAlpha }});
      }});

      var avgPtsM    = n? (sumPtsMoy/n) : 0;
      var avgPts100k = n? (sumPts100k/n) : 0;
      var avgAlpha   = n? (sumAlpha/n) : 0;
      var pctEtr     = n? (100 * nbEtr / n) : 0;

      var html = "";
      html += "<div class='col-12 col-lg-8'><div class='row g-3'>";
      html += "<div class='col-6 col-md-4'><div class='card p-3'><div class='small text-secondary'>Effectif filtré</div><div class='h5 m-0'>"+ n +"</div></div></div>";
      html += "<div class='col-6 col-md-4'><div class='card p-3'><div class='small text-secondary'>Valeur totale</div><div class='h5 m-0'>"+ Math.round(sumValeur).toLocaleString('fr-CH') +"</div></div></div>";
      html += "<div class='col-6 col-md-4'><div class='card p-3'><div class='small text-secondary'>Pts moy. (équipe)</div><div class='h5 m-0'>"+ avgPtsM.toFixed(2) +"</div></div></div>";
      html += "<div class='col-6 col-md-4'><div class='card p-3'><div class='small text-secondary'>Pts / 100k (moy.)</div><div class='h5 m-0'>"+ avgPts100k.toFixed(2) +"</div></div></div>";
      html += "<div class='col-6 col-md-4'><div class='card p-3'><div class='small text-secondary'>AlphaScore (moy.)</div><div class='h5 m-0'>"+ avgAlpha.toFixed(1) +"</div></div></div>";
      html += "<div class='col-6 col-md-4'><div class='card p-3'><div class='small text-secondary'>Étrangers</div><div class='h5 m-0'>"+ nbEtr +" <span class='small text-secondary'>("+ pctEtr.toFixed(1) +"%)</span></div></div></div>";
      html += "</div></div>";

      html += "<div class='col-12 col-lg-4'><div class='card p-3'><div class='small text-secondary mb-2'>Répartition par poste</div>";
      html += "<table class='table table-sm m-0'><thead><tr><th>Poste</th><th>#</th></tr></thead><tbody>";
      html += "<tr><td>C</td><td>"+c+"</td></tr>";
      html += "<tr><td>W</td><td>"+w+"</td></tr>";
      html += "<tr><td>D</td><td>"+d+"</td></tr>";
      html += "<tr><td>G</td><td>"+g+"</td></tr>";
      html += "</tbody></table></div></div>";

      summary.innerHTML = html;

      players.sort(function(a,b){{ return (b.alpha||0) - (a.alpha||0); }});
      var top5 = players.slice(0,5);
      if (!top5.length) {{
        top5Div.innerHTML = "<span class='text-secondary'>—</span>";
      }} else {{
        var rows = "";
        top5.forEach(function(p){{
          rows += "<tr><td>"+p.joueur+"</td><td>"+p.poste+"</td><td>"+p.equipe+"</td><td>"+ (p.valeur||0).toLocaleString('fr-CH') +"</td><td>"+ (p.ptsm!=null? p.ptsm.toFixed(2): '—') +"</td><td>"+ (p.alpha!=null? p.alpha.toFixed(1): '—') +"</td></tr>";
      }});
        top5Div.innerHTML = "<div class='table-wrapper'><table class='table table-sm w-100'><thead><tr><th>Joueur</th><th>Poste</th><th>Équipe</th><th>Valeur</th><th>Pts moy.</th><th>AlphaScore</th></tr></thead><tbody>"+rows+"</tbody></table></div>";
      }}
    }}

    // première exécution + listeners
    recalc();
    ownerSel.addEventListener('change', recalc);
    teamSel.addEventListener('change', recalc);

    return {{ refresh: recalc }};
  }}

</script>
</body></html>"""

def df_to_html_table(df: pd.DataFrame, table_id: str, quick_placeholder="Filtrer…") -> str:
    if df is None or df.empty:
        return "<div class='text-secondary'>Aucune donnée à afficher.</div>"
    df2 = df.copy().where(pd.notna(df), "")

    drop_cols = [c for c in df2.columns if c.strip().lower() in ("id","id joueur","player id","player_id")]
    if drop_cols:
        df2 = df2.drop(columns=drop_cols)

    cols = list(df2.columns)
    thead = "<thead><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead>"

    rows_html = []
    for _, r in df2.iterrows():
        tds = []
        for c in cols:
            if c.lower().strip() == "mv spark":
                tds.append(f"<td class='spark-cell'>{r[c]}</td>")
            else:
                tds.append(f"<td>{r[c]}</td>")
        rows_html.append("<tr>" + "".join(tds) + "</tr>")

    tbody = "<tbody>" + "".join(rows_html) + "</tbody>"
    quick = f"""
<div class="d-flex align-items-center gap-2 mb-2">
  <span class="small text-secondary">Recherche rapide :</span>
  <input data-quickfilter-table="{table_id}" class="form-control form-control-sm" placeholder="{quick_placeholder}" style="max-width:280px">
</div>"""
    return f"""{quick}
<div class="table-wrapper">
  <table id="{table_id}" class="table table-sm w-100">
    {thead}{tbody}
  </table>
</div>"""

def kv_table(headers, rows) -> str:
    head = "<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>"
    body = "<tbody>" + "".join("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in rows) + "</tbody>"
    return f"<table class='table table-sm w-100'>{head}{body}</table>"

# ----------------- HELPERS -----------------
def require(v, name):
    if not v:
        print(f"❌ Variable manquante: {name} (cf. .env)")
        sys.exit(1)
    return v

def login_session():
    require(EMAIL, "TOPS_EMAIL")
    require(PASSWORD, "TOPS_PASSWORD")
    s = requests.Session()
    s.headers.update(HEADERS_COMMON)
    r0 = s.get(f"{BASE}/sanctum/csrf-cookie", timeout=15)
    r0.raise_for_status()
    csrf = s.cookies.get("XSRF-TOKEN")
    if not csrf:
        raise RuntimeError("Pas de XSRF-TOKEN (CSRF).")
    s.headers["X-XSRF-TOKEN"] = unquote(csrf)
    payload = {"email": EMAIL, "password": PASSWORD}
    r1 = s.post(f"{BASE}/api/login", json=payload, timeout=20)
    if r1.status_code == 419:
        raise RuntimeError("419 CSRF mismatch — vérifie headers/cookies.")
    r1.raise_for_status()
    return s

def sanitize_for_html(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    df2 = df.copy()
    if "offers" in df2.columns:
        df2["Offres (#)"] = df2["offers"].apply(lambda v: len(v) if isinstance(v, list) else 0)
        df2 = df2.drop(columns=["offers"])
    drop_cols = [c for c in df2.columns if any(k in c for k in ["portrait_image","logo","logo_lg","portrait_image_lg"])]
    if drop_cols:
        df2 = df2.drop(columns=drop_cols)
    for c in df2.columns:
        df2[c] = df2[c].apply(lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":")) if isinstance(x,(list,dict)) else x)
    return df2

def _parse_ids_list(env_str):
    out = []
    if not env_str: return out
    for tok in env_str.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok: continue
        try: out.append(int(tok))
        except: pass
    return list(dict.fromkeys(out))

def _parse_team_ids_env(env_str: str, fallback_ids):
    if not env_str:
        return list(dict.fromkeys(fallback_ids))
    out = []
    for tok in env_str.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok: continue
        try: out.append(int(tok))
        except: pass
    return list(dict.fromkeys(out)) or list(dict.fromkeys(fallback_ids))

def _parse_owner_name_overrides(env_str):
    m = {}
    if not env_str: return m
    for part in env_str.split(","):
        part = part.strip()
        if "=" in part:
            k,v = part.split("=",1)
            try: m[int(k.strip())] = v.strip()
            except: pass
    return m

# ---- NUMERIC SAFETY HELPERS ----
def _num_series(df: pd.DataFrame, col: str):
    if isinstance(df, pd.DataFrame) and col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    if isinstance(df, pd.Series):
        return pd.to_numeric(df, errors="coerce")
    try:
        n = len(df)
        return pd.Series([np.nan]*n, index=df.index, dtype="float64")
    except Exception:
        return pd.Series(dtype="float64")

def _winsor_rankpct(s: pd.Series, lo=0.05, hi=0.95):
    s = pd.to_numeric(s, errors="coerce")
    if isinstance(s, pd.Series): x = s.copy()
    else: x = pd.Series([s], dtype="float64")
    if x.dropna().empty:
        return pd.Series([None]*len(x), index=x.index)
    ql, qh = x.quantile(lo), x.quantile(hi)
    x = x.clip(lower=ql, upper=qh)
    ranks = x.rank(pct=True)
    return ranks

def _safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return a / b.replace({0: np.nan})

def _asfloat(s, fill=0.0):
    if isinstance(s, pd.Series):
        return pd.to_numeric(s, errors="coerce").fillna(fill).astype(float)
    try:
        return float(s)
    except Exception:
        return float(fill)

def _round_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return df
    df = df.copy()
    num_cols = df.select_dtypes(include="number").columns.tolist()
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    return df

def blended_form(cur_avg, n1_avg, n2_avg, w_cur=FORM_W_CUR, w_n1=FORM_W_N1, w_n2=FORM_W_N2):
    vals, w = [], 0.0
    if pd.notna(cur_avg): vals.append((float(cur_avg), w_cur)); w += w_cur
    if pd.notna(n1_avg):  vals.append((float(n1_avg),  w_n1));  w += w_n1
    if pd.notna(n2_avg):  vals.append((float(n2_avg),  w_n2));  w += w_n2
    if not vals or w == 0: return None
    return sum(v*wt for v,wt in vals) / w

# ----------------- PRICE HISTORY -----------------
def _parse_marketvalue_series(detail_json: dict) -> pd.Series:
    if not isinstance(detail_json, dict):
        return pd.Series(dtype="float64")
    d = detail_json.get("data") if "data" in detail_json else detail_json
    mv = d.get("marketvalue_metrics") or []
    if not isinstance(mv, list) or not mv:
        return pd.Series(dtype="float64")
    try:
        dt_index = pd.to_datetime([x.get("measured_at") for x in mv], utc=True, errors="coerce")
        vals     = pd.to_numeric([x.get("measured_value") for x in mv], errors="coerce")
        s = pd.Series(vals, index=dt_index).dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s
    except Exception:
        return pd.Series(dtype="float64")

def _spark_svg(series: pd.Series, width=180, height=40, stroke="#19C37D") -> str:
    if series is None or series.empty:
        return ""
    s = series.dropna().astype(float)
    if s.empty:
        return ""
    x = np.linspace(0, width, num=len(s))
    y_raw = s.values
    y_min, y_max = float(np.min(y_raw)), float(np.max(y_raw))
    if y_max == y_min:
        y = np.full_like(x, height/2.0)
    else:
        y = height - ((y_raw - y_min) / (y_max - y_min)) * (height - 4) - 2
    points = " ".join(f"{x[i]:.1f},{y[i]:.1f}" for i in range(len(x)))
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <polyline fill="none" stroke="{stroke}" stroke-width="2" points="{points}"/>
</svg>"""

def _price_features_from_series(s: pd.Series):
    if s is None or s.empty:
        return None, None, None, None, ""
    now = pd.Timestamp.now(tz="UTC")
    s = s.sort_index()
    s90   = s.loc[s.index >= (now - pd.Timedelta(days=90))]
    mv90  = float(s90.mean()) if not s90.empty else float(s.mean())
    s365  = s.loc[s.index >= (now - pd.Timedelta(days=365))]
    mvmax = float(s365.max()) if not s365.empty else float(s.max())
    mvmin = float(s365.min()) if not s365.empty else float(s.min())
    s_tail = s.loc[s.index >= (now - pd.Timedelta(days=PRICE_MOMENTUM_DAYS))]
    momentum = None
    if len(s_tail) >= 2:
        first = float(s_tail.iloc[0]); last  = float(s_tail.iloc[-1])
        if first != 0: momentum = (last - first) / abs(first) * 100.0
    swin = s.loc[s.index >= (now - pd.Timedelta(days=PRICE_WINDOW_DAYS))]
    if swin.empty: swin = s
    swin = swin.ffill(limit=3)
    spark = _spark_svg(swin)
    return mv90, mvmax, mvmin, momentum, spark

# ----------------- API FETCHES -----------------
def fetch_player_detail(s, player_id:int) -> dict:
    r = s.get(f"{BASE}/api/players/{player_id}", timeout=20)
    if r.status_code == 404:
        return {"data": None, "error": "not_found", "player_id": player_id}
    if r.status_code != 200:
        time.sleep(0.3); r = s.get(f"{BASE}/api/players/{player_id}", timeout=20)
    r.raise_for_status()
    return r.json()

def parse_player_seasons(detail_json: dict):
    out = {"cur_games": None, "cur_avg": None, "n1_games": None, "n1_avg": None, "n2_games": None, "n2_avg": None}
    if not isinstance(detail_json, dict): return out
    d = detail_json.get("data") if "data" in detail_json else detail_json
    pm = d.get("point_metrics") or []
    if not isinstance(pm, list) or not pm:
        ss = d.get("stats_summary") or []
        smap = {x.get("key"): x.get("value") for x in ss if isinstance(x, dict)}
        out["cur_games"] = smap.get("games")
        out["cur_avg"] = d.get("points_avg")
        return out
    try:
        pm_sorted = sorted(pm, key=lambda x: x.get("season", 0), reverse=True)
    except Exception:
        pm_sorted = pm

    def _avg_safe(x):
        if x is None: return None
        if "points_avg" in x and x["points_avg"] is not None:
            return x["points_avg"]
        try:
            pts = float(x.get("points")) if x.get("points") is not None else None
            gms = float(x.get("games")) if x.get("games") is not None else None
            if pts is not None and gms and gms > 0: return pts / gms
        except Exception:
            pass
        return None

    slots = [("cur_", 0), ("n1_", 1), ("n2_", 2)]
    for prefix, idx in slots:
        if idx < len(pm_sorted):
            item = pm_sorted[idx]
            out[prefix + "games"] = item.get("games")
            out[prefix + "avg"]   = _avg_safe(item)
    if out["cur_avg"] is None and d.get("points_avg") is not None:
        out["cur_avg"] = d.get("points_avg")
    return out

def fetch_rankings_maps(s):
    try:
        r = s.get(f"{BASE}/api/rankings", timeout=20)
        if r.status_code != 200: return {}, {}, {}
        j = r.json()
        data = j.get("data") or {}
        teams = data.get("teams") or []
        games_by_id, acr_by_id, pav_by_id = {}, {}, {}
        for t in teams:
            tid = t.get("id")
            if tid is None: continue
            tid = int(tid)
            games_by_id[tid] = t.get("games")
            acr_by_id[tid]   = t.get("acronym") or t.get("name")
            pav = t.get("points_avg")
            try: pav_by_id[tid] = float(pav) if pav is not None else None
            except: pav_by_id[tid] = None
        return games_by_id, acr_by_id, pav_by_id
    except Exception:
        return {}, {}, {}

def _extract_username_from_payload(d):
    if not isinstance(d, dict): return ""
    v = d.get("username")
    if isinstance(v, str) and v.strip(): return v.strip()
    for k in ("user","owner","account"):
        obj = d.get(k)
        if isinstance(obj, dict):
            for kk in ("username","name","display_name","nickname"):
                v = obj.get(kk)
                if isinstance(v,str) and v.strip(): return v.strip()
    return ""

def fetch_my_team_views(s):
    try:
        j = None
        if TEAM_ID:
            r = s.get(f"{BASE}/api/user/teams/{TEAM_ID}", timeout=20)
            if r.status_code == 200: j = r.json()
        if j is None and TEAM_QUERY:
            r = s.get(f"{BASE}/api/user/teams", params={"team": TEAM_QUERY}, timeout=20)
            if r.status_code == 200: j = r.json()
        if not j: return pd.DataFrame(), pd.DataFrame(), ""
        data = j.get("data", j)
        if isinstance(data, list): data = data[0] if data else {}
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), ""

    my_username = _extract_username_from_payload(data)
    players = data.get("players", []) or []
    lineup  = data.get("lineup", []) or []

    rows = []
    for p in players:
        team = (p.get("team") or {})
        rows.append({
            "ID": p.get("id"),
            "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "Poste": p.get("position_name"),
            "Équipe": team.get("acronym") or team.get("name"),
            "Points": p.get("points"),
            "Pts moy.": p.get("points_avg"),
            "Valeur": p.get("marketvalue"),
            "Étranger": "Étranger" if bool(p.get("is_foreigner")) else "",
        })
    df_effectif = pd.DataFrame(rows)

    id2name = {p.get("id"): f"{p.get('firstname','')} {p.get('lastname','')}".strip() for p in players}
    line_rows = []
    for slot in lineup:
        pos_id = slot.get("position_id")
        cur_id = slot.get("current")
        avail  = slot.get("available") or []
        pool   = slot.get("lined_up") or []
        line_rows.append({
            "Slot": pos_id,
            "Actuel": id2name.get(cur_id, cur_id),
            "Banc dispo (#)": len(avail),
            "Candidats (#)": len(pool),
        })
    df_lineup = pd.DataFrame(line_rows).sort_values("Slot")
    return df_effectif, df_lineup, my_username

def fetch_team_username(s, team_id:int) -> str:
    try:
        tid = int(team_id)
    except Exception:
        return ""
    if tid in TEAM_USERNAME_CACHE:
        return TEAM_USERNAME_CACHE[tid]
    try:
        r = s.get(f"{BASE}/api/user/teams/{tid}/stats", timeout=15)
        if r.status_code == 200:
            j = r.json()
            d = j.get("data", j)
            u = (d.get("username") or "").strip()
            TEAM_USERNAME_CACHE[tid] = u
            return u
    except Exception:
        pass
    try:
        r = s.get(f"{BASE}/api/user/teams/{tid}", timeout=15)
        if r.status_code == 200:
            j = r.json()
            d = j.get("data", j)
            u = (d.get("username") or "").strip()
            if not u and isinstance(d.get("user"), dict):
                u = (d["user"].get("username") or d["user"].get("name") or "").strip()
            TEAM_USERNAME_CACHE[tid] = u
            return u
    except Exception:
        pass
    TEAM_USERNAME_CACHE[tid] = ""
    return ""

def fetch_players_of_user_team(s, team_id:int):
    try:
        r = s.get(f"{BASE}/api/user/teams/{team_id}/players", timeout=20)
        if r.status_code != 200:
            return []
        j = r.json()
        data = j.get("data", j)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def build_owners_index(s, my_effectif_df: pd.DataFrame, other_team_ids: list, owner_overrides: dict, my_username: str):
    owners = {}
    me_label = my_username if SHOW_ME_AS_USERNAME and my_username else "Moi"
    if my_effectif_df is not None and not my_effectif_df.empty and "ID" in my_effectif_df.columns:
        try:
            for pid in pd.to_numeric(my_effectif_df["ID"], errors="coerce").dropna().astype(int).tolist():
                owners[pid] = me_label
        except Exception:
            pass
    for tid in other_team_ids:
        username = fetch_team_username(s, tid) or owner_overrides.get(tid, "")
        label = username if username else f"Équipe {tid}"
        players = fetch_players_of_user_team(s, tid)
        for p in players:
            pid = p.get("id")
            if isinstance(pid, int):
                owners[pid] = label
        time.sleep(0.05)
    return owners

def fetch_team_roster(s, team_id: int) -> list:
    try:
        r = s.get(f"{BASE}/api/players", params={"team": int(team_id)}, timeout=20)
        if r.status_code != 200:
            return []
        j = r.json()
        data = j.get("data", j)
        return data if isinstance(data, list) else []
    except Exception:
        return []

# ----------------- ALPHASCORE (affiché seulement) -----------------
def compute_alpha_score(df):
    if df is None or df.empty: return df
    df = df.copy()

    disc   = _num_series(df, "Décote (%)")
    eff    = _num_series(df, "Pts / 100k")
    cur    = _num_series(df, "Pts moy. (saison)")
    base   = _num_series(df, "Pts moy.")
    cur    = cur.fillna(base)

    n1     = _num_series(df, "Pts moy. N-1")
    n2     = _num_series(df, "Pts moy. N-2")
    m_j    = _num_series(df, "Matchs (saison)")
    m_t    = _num_series(df, "Matchs (équipe)")
    usage  = _safe_div(m_j, m_t)
    team_ctx = _num_series(df, "Team PtsAvg") if "Team PtsAvg" in df.columns else pd.Series([np.nan]*len(df), index=df.index, dtype="float64")
    offers = _num_series(df, "Offres (#)") if "Offres (#)" in df.columns else pd.Series([np.nan]*len(df), index=df.index, dtype="float64")
    exp_s  = _num_series(df, "Expire dans (s)") if "Expire dans (s)" in df.columns else pd.Series([np.nan]*len(df), index=df.index, dtype="float64")

    if "Étranger" in df.columns:
        is_foreigner = df["Étranger"].astype(str).str.lower().str.contains("étranger")
    else:
        is_foreigner = pd.Series([False]*len(df), index=df.index)

    form_multi = []
    for a,b,c in zip(cur, n1, n2):
        form_multi.append(blended_form(a, b, c))
    df["Forme (multi)"] = pd.Series(form_multi, index=df.index)

    tmp_cons = []
    for a,b,c in zip(cur, n1, n2):
        arr = [v for v in [a,b,c] if pd.notna(v)]
        if len(arr) < 2: tmp_cons.append(None)
        else:
            s = pd.Series(arr); std = s.std()
            tmp_cons.append(1/(1+std) if std==std else None)
    df["Régularité"] = pd.Series(tmp_cons, index=df.index)

    n_disc  = _asfloat(_winsor_rankpct(disc))
    n_eff   = _asfloat(_winsor_rankpct(eff))
    n_form  = _asfloat(_winsor_rankpct(df["Forme (multi)"]))
    n_cons  = _asfloat(_winsor_rankpct(df["Régularité"]))
    n_usage = _asfloat(_winsor_rankpct(usage))
    n_ctx   = _asfloat(_winsor_rankpct(team_ctx)) if team_ctx is not None else _asfloat(pd.Series([None]*len(df), index=df.index))

    market_adj = pd.Series(0.0, index=df.index, dtype="float64")
    if "Offres (#)" in df.columns:
        market_adj = market_adj - OFFERS_PENALTY*(_asfloat(offers)>0).astype(float)
    if "Expire dans (s)" in df.columns:
        hours = _asfloat(exp_s)/3600.0
        soon  = (hours <= EXPIRY_BOOST_HRS).astype(float)
        market_adj = market_adj + 0.01*soon

    foreign_adj = - FOREIGNER_PENALTY * _asfloat(is_foreigner.astype(float))

    base_score = (
        ALPHA_W_VALUE   * n_disc +
        ALPHA_W_EFF     * n_eff  +
        ALPHA_W_FORM    * n_form +
        ALPHA_W_CONSIST * n_cons +
        ALPHA_W_USAGE   * n_usage+
        ALPHA_W_CTX     * n_ctx
    )
    score = base_score + (ALPHA_W_MARKET * _asfloat(market_adj)) + _asfloat(foreign_adj)
    score = _asfloat(score).clip(lower=0.0, upper=1.0)
    df["AlphaScore"] = (score*100.0).round(1)

    # Badges → en rendu HTML final uniquement (pas ici)
    if "Étranger" in df.columns:
        df["Étranger"] = df["Étranger"].apply(lambda x: "Étranger" if isinstance(x,str) and x.strip() else "")
    if "Propriétaire" in df.columns:
        df["Propriétaire"] = df["Propriétaire"].astype(str).str.strip()

    df["Usage"] = _safe_div(_num_series(df,"Matchs (saison)"),
                            _num_series(df,"Matchs (équipe)")).round(3)
    return _round_metrics(df).sort_values("AlphaScore", ascending=False)

# ----------------- MARKET ENRICHED -----------------
def fetch_market_enriched(s):
    r = s.get(f"{BASE}/api/user/leagues/{LEAGUE_ID}/transfers", timeout=20)
    r.raise_for_status()
    j = r.json()
    items = j.get("data")
    if items is None:
        for _, v in j.items():
            if isinstance(v, list): items=v; break
    if items is None: items=[]
    if isinstance(items, dict): items=[items]
    base = pd.json_normalize(items, sep='.')
    print(f"[fetch_market] rows={len(base)} cols={len(base.columns)}")

    if "player.marketvalue" in base.columns and "price" in base.columns:
        mv = pd.to_numeric(base["player.marketvalue"], errors="coerce")
        pr = pd.to_numeric(base["price"], errors="coerce")
        base["discount"] = mv.fillna(0) - pr.fillna(0)
        base["discount_pct"] = (base["discount"] / mv.replace(0, np.nan)) * 100
    if "player.points_avg" in base.columns and "price" in base.columns:
        pts = pd.to_numeric(base["player.points_avg"], errors="coerce")
        pr  = pd.to_numeric(base["price"], errors="coerce")
        base["ratio_pts_per_100k"] = pts.fillna(0) / (pr.replace(0, np.nan)/100000)

    if "player.team.acronym" in base.columns and "team.acronym" not in base.columns:
        base["team.acronym"] = base["player.team.acronym"]
    if "player.team.name" in base.columns and "team.name" not in base.columns:
        base["team.name"] = base["player.team.name"]
    if "player.team.id" in base.columns and "team.id" not in base.columns:
        base["team.id"] = base["player.team.id"]
    if "player.name" not in base.columns:
        base["player.name"] = base.get("player.firstname","").fillna("").astype(str) + " " + base.get("player.lastname","").fillna("").astype(str)

    team_games_map, _, team_ptsavg_map = fetch_rankings_maps(s)
    base["Matchs (équipe)"] = pd.to_numeric(base.get("team.id"), errors="coerce").map(lambda v: team_games_map.get(int(v)) if pd.notna(v) else None)
    base["Team PtsAvg"]     = pd.to_numeric(base.get("team.id"), errors="coerce").map(lambda v: team_ptsavg_map.get(int(v)) if pd.notna(v) else None)

    add = []
    for pid in pd.to_numeric(base.get("player.id"), errors="coerce").dropna().astype(int).unique().tolist():
        rec = {"player.id": pid}
        try:
            det = fetch_player_detail(s, pid)
            seas = parse_player_seasons(det)
            rec.update({
                "Matchs (saison)": seas["cur_games"],
                "Pts moy. (saison)": seas["cur_avg"],
                "Matchs N-1": seas["n1_games"],
                "Pts moy. N-1": seas["n1_avg"],
                "Matchs N-2": seas["n2_games"],
                "Pts moy. N-2": seas["n2_avg"],
            })
            if ADD_PRICE_FEATURES:
                s_hist = _parse_marketvalue_series(det)
                mv90, mvmax, mvmin, momentum, spark = _price_features_from_series(s_hist)
                rec.update({
                    "MV_90": mv90,
                    "MV_MAX_365": mvmax,
                    "MV_MIN_365": mvmin,
                    "MV_MOMENTUM_30": momentum,
                    "MV_SPARK_HTML": spark
                })
        except Exception:
            pass
        add.append(rec)
        time.sleep(0.04)
    df_add = pd.DataFrame(add)
    base = df_add.merge(base, on="player.id", how="right")

    if "price" in base.columns and "MV_MAX_365" in base.columns:
        base["discount_vs_max365_pct"] = ((pd.to_numeric(base["MV_MAX_365"], errors="coerce") - pd.to_numeric(base["price"], errors="coerce")) /
                                          pd.to_numeric(base["MV_MAX_365"], errors="coerce").replace(0, np.nan)) * 100

    df_disp = base.copy()
    if "offers" in df_disp.columns:
        df_disp["Offres (#)"] = df_disp["offers"].apply(lambda v: len(v) if isinstance(v, list) else 0)
        df_disp = df_disp.drop(columns=["offers"])

    if "MV_SPARK_HTML" in df_disp.columns:
        df_disp["MV Spark"] = df_disp["MV_SPARK_HTML"].fillna("").astype(str)
    if "player.is_foreigner" in df_disp.columns:
        df_disp["player.is_foreigner"] = df_disp["player.is_foreigner"].fillna(False).astype(bool).map(lambda x: "Étranger" if x else "")

    nice = {
        "player.name":"Joueur","player.position_name":"Poste","team.acronym":"Équipe","player.is_foreigner":"Étranger",
        "price":"Prix","player.marketvalue":"Valeur marchée","discount_pct":"Décote (%)","ratio_pts_per_100k":"Pts / 100k",
        "player.points_avg":"Pts moy.","username":"Vendeur","expires_in":"Expire dans (s)",
        "MV_90": "MV 90 j", "MV_MAX_365":"MV max 365 j", "MV_MIN_365":"MV min 365 j", "MV_MOMENTUM_30":"Momentum 30 j (%)",
        "discount_vs_max365_pct":"Décote vs max 365 (%)"
    }

    keep_cols = [c for c in [
        "player.name","player.position_name","team.acronym","player.is_foreigner",
        "price","player.marketvalue","discount_pct","ratio_pts_per_100k","player.points_avg",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Matchs N-1","Pts moy. N-1","Matchs N-2","Pts moy. N-2","Team PtsAvg",
        "MV_90","MV_MIN_365","MV_MAX_365","MV_MOMENTUM_30","discount_vs_max365_pct","MV Spark",
        "username","expires_in"
    ] if c in df_disp.columns]
    df_disp = df_disp[keep_cols].rename(columns=nice)

    return sanitize_for_html(df_disp), base

# ----------------- DECISION SCORE (internes recos) -----------------
DECISION_W_PERF, DECISION_W_ROLE, DECISION_W_PHYS, DECISION_W_CONTR = 0.30, 0.25, 0.20, 0.25
def _norm_rank(s):
    r = _winsor_rankpct(s)
    r = r if isinstance(r, pd.Series) else pd.Series([r])
    return r.fillna(0).clip(lower=0, upper=1)

def compute_decision_score(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    pts_cur   = _num_series(out, "Pts moy. (saison)").fillna(_num_series(out, "Pts moy."))
    forme     = _num_series(out, "Forme (multi)") if "Forme (multi)" in out.columns else _num_series(out, "Pts moy.")
    reg       = _num_series(out, "Régularité") if "Régularité" in out.columns else _num_series(out, "Pts moy.")
    usage     = _num_series(out, "Usage") if "Usage" in out.columns else _num_series(out, "Pts moy.")
    team_ctx  = _num_series(out, "Team PtsAvg") if "Team PtsAvg" in out.columns else _num_series(out, "Pts moy.")
    eff_cost  = _num_series(out, "Pts / 100k")
    discount  = _num_series(out, "Décote (%)")
    disc_vmax = _num_series(out, "Décote vs max 365 (%)") if "Décote vs max 365 (%)" in out.columns else None
    offers    = _num_series(out, "Offres (#)") if "Offres (#)" in out.columns else pd.Series(0.0, index=out.index, dtype="float64")
    expires_s = _num_series(out, "Expire dans (s)") if "Expire dans (s)" in out.columns else pd.Series(float("nan"), index=out.index, dtype="float64")
    is_foreigner = out["Étranger"].astype(str).str.contains("Étranger", case=False) if "Étranger" in out.columns else pd.Series([False]*len(out), index=out.index)

    perf = 0.55*_norm_rank(pts_cur) + 0.25*_norm_rank(forme) + 0.20*_norm_rank(usage)
    role = 0.7*_norm_rank(team_ctx) + 0.3*_norm_rank(usage)
    phys = 0.65*_norm_rank(reg) + 0.35*_norm_rank(usage)
    if disc_vmax is not None:
        contr_market = 0.45*_norm_rank(eff_cost) + 0.30*_norm_rank(discount) + 0.25*_norm_rank(disc_vmax)
    else:
        contr_market = 0.55*_norm_rank(eff_cost) + 0.35*_norm_rank(discount)
    contr_market = contr_market - 0.15 * is_foreigner.astype(float)
    soon = (expires_s <= EXPIRY_BOOST_HRS*3600).fillna(False).astype(float)
    contr_market = contr_market + 0.03*soon - 0.02*(offers.fillna(0) > 0).astype(float)

    decision = (
        DECISION_W_PERF  * perf +
        DECISION_W_ROLE  * role +
        DECISION_W_PHYS  * phys +
        DECISION_W_CONTR * contr_market
    )
    out["__ScoreDecision"] = (pd.to_numeric(decision, errors="coerce").fillna(0.0).clip(0,1)*100).round(1)
    return out

def pick_recommendations(df, budget, foreign_slots, needs_by_pos):
    if df is None or df.empty:
        return pd.DataFrame(), 0
    work  = df.copy()
    if "__ScoreDecision" not in work.columns:
        work = compute_decision_score(work)
    price = _num_series(work, "Prix").fillna(0)
    score = _num_series(work, "__ScoreDecision").fillna(0)
    dens  = score / price.replace(0, np.nan)
    work["__dens"] = dens.fillna(0)
    work = work.sort_values(["__dens","__ScoreDecision"], ascending=[False, False])

    pos = work["Poste"].astype(str).str.upper() if "Poste" in work.columns else pd.Series([""]*len(work), index=work.index)
    def fam(p):
        p = p.strip()
        if p.startswith("G"): return "G"
        if p.startswith("D"): return "D"
        if p.startswith("C"): return "C"
        if "W" in p or "AIL" in p: return "W"
        return "W"
    fams = pos.map(fam)

    is_foreigner = work["Étranger"].astype(str).str.contains("Étranger", case=False) if "Étranger" in work.columns else pd.Series([False]*len(work), index=work.index)

    take_idx, spent, used_foreign = [], 0, 0
    used_by_pos = {"C":0,"W":0,"D":0,"G":0}

    for i, row in work.iterrows():
        p = float(_num_series(work.loc[[i]], "Prix").iloc[0] or 0)
        if p<=0 or spent + p > budget:
            continue
        f = fams.loc[i]
        if used_by_pos[f] >= needs_by_pos.get(f, 999):
            continue
        if bool(is_foreigner.loc[i]) and used_foreign + 1 > foreign_slots:
            continue

        take_idx.append(i)
        spent += p
        used_by_pos[f] += 1
        if bool(is_foreigner.loc[i]): used_foreign += 1

    sel = work.loc[take_idx].drop(columns=["__dens"]) if take_idx else pd.DataFrame()
    return sel, spent

# ----------------- RECOMMENDATION ENGINE V2 -----------------
def _projected_points(df: pd.DataFrame) -> pd.Series:
    """Projection conservative qui privilégie la saison courante sans ignorer l'historique."""
    cur = _num_series(df, "Pts moy. (saison)").fillna(_num_series(df, "Pts moy."))
    n1 = _num_series(df, "Pts moy. N-1")
    n2 = _num_series(df, "Pts moy. N-2")
    projected = []
    for a, b, c in zip(cur, n1, n2):
        blended = blended_form(a, b, c)
        projected.append(blended if blended is not None else (float(a) if pd.notna(a) else np.nan))
    return pd.Series(projected, index=df.index, dtype="float64")

def _fair_value(df: pd.DataFrame) -> pd.Series:
    """Valeur juste robuste à partir du marché courant et de l'historique disponible."""
    current = _num_series(df, "Valeur marchée")
    mv90 = _num_series(df, "MV 90 j")
    mvmin = _num_series(df, "MV min 365 j")
    mvmax = _num_series(df, "MV max 365 j")
    out = []
    for idx in df.index:
        refs = []
        if pd.notna(current.loc[idx]) and current.loc[idx] > 0:
            refs.append((float(current.loc[idx]), 0.50))
        if pd.notna(mv90.loc[idx]) and mv90.loc[idx] > 0:
            refs.append((float(mv90.loc[idx]), 0.35))
        if pd.notna(mvmin.loc[idx]) and pd.notna(mvmax.loc[idx]) and mvmax.loc[idx] > 0:
            refs.append(((float(mvmin.loc[idx]) + float(mvmax.loc[idx])) / 2.0, 0.15))
        if refs:
            weight = sum(w for _, w in refs)
            out.append(sum(v * w for v, w in refs) / weight)
        else:
            out.append(np.nan)
    return pd.Series(out, index=df.index, dtype="float64")

def _confidence_score(df: pd.DataFrame) -> pd.Series:
    games = _num_series(df, "Matchs (saison)").fillna(0).clip(lower=0)
    game_evidence = (games / 20.0).clip(upper=1.0)
    season_evidence = (
        _num_series(df, "Pts moy. (saison)").notna().astype(float)
        + _num_series(df, "Pts moy. N-1").notna().astype(float)
        + _num_series(df, "Pts moy. N-2").notna().astype(float)
    ) / 3.0
    history_evidence = (
        _num_series(df, "MV 90 j").notna().astype(float)
        + _num_series(df, "MV min 365 j").notna().astype(float)
        + _num_series(df, "MV max 365 j").notna().astype(float)
    ) / 3.0
    return ((0.45 * game_evidence + 0.25 * season_evidence + 0.30 * history_evidence) * 100).clip(0, 100)

def _replacement_index(roster: pd.DataFrame, family: str):
    if roster is None or roster.empty or "Poste" not in roster.columns:
        return None
    families = roster["Poste"].astype(str).map(pos_family_label)
    compatible = roster.loc[families == family]
    if compatible.empty:
        return None
    projected = _projected_points(compatible)
    if projected.dropna().empty:
        return compatible.index[0]
    return projected.fillna(float("inf")).idxmin()

def compute_recommendations_v2(market: pd.DataFrame, roster: pd.DataFrame) -> pd.DataFrame:
    if market is None or market.empty:
        return pd.DataFrame()
    out = market.copy()
    out["Projection pts"] = _projected_points(out)
    out["Valeur estimée"] = _fair_value(out)
    out["Confiance (%)"] = _confidence_score(out)

    price = _num_series(out, "Prix").fillna(0)
    fair = _num_series(out, "Valeur estimée")
    out["Profit potentiel"] = (fair - price).round(0)
    out["ROI potentiel (%)"] = (_safe_div(fair - price, price) * 100).round(1)

    replacement_names, replacement_points, replacement_foreign = [], [], []
    for idx, row in out.iterrows():
        family = pos_family_label(str(row.get("Poste", "")))
        ridx = _replacement_index(roster, family)
        if ridx is None:
            replacement_names.append("Place libre")
            replacement_points.append(0.0)
            replacement_foreign.append(False)
            continue
        rrow = roster.loc[ridx]
        rproj = _projected_points(roster.loc[[ridx]]).iloc[0]
        replacement_names.append(str(rrow.get("Joueur", "—")))
        replacement_points.append(float(rproj) if pd.notna(rproj) else 0.0)
        replacement_foreign.append("étranger" in str(rrow.get("Étranger", "")).lower())

    out["Remplace"] = replacement_names
    out["Pts remplacé"] = replacement_points
    out["Gain pts/match"] = (_num_series(out, "Projection pts") - _num_series(out, "Pts remplacé")).round(2)

    projection = _num_series(out, "Projection pts")
    gain = _num_series(out, "Gain pts/match")
    usage = _safe_div(_num_series(out, "Matchs (saison)"), _num_series(out, "Matchs (équipe)"))
    team_context = _num_series(out, "Team PtsAvg")
    score_team = (
        0.40 * _norm_rank(projection)
        + 0.40 * _norm_rank(gain)
        + 0.10 * _norm_rank(usage)
        + 0.10 * _norm_rank(team_context)
    ) * 100

    roi = _num_series(out, "ROI potentiel (%)")
    discount = _num_series(out, "Décote (%)")
    momentum = _num_series(out, "Momentum 30 j (%)")
    history_discount = _num_series(out, "Décote vs max 365 (%)")
    score_trading = (
        0.45 * _norm_rank(roi)
        + 0.25 * _norm_rank(discount)
        + 0.20 * _norm_rank(history_discount)
        + 0.10 * _norm_rank(momentum)
    ) * 100

    out["Score équipe"] = score_team.round(1)
    out["Score trading"] = score_trading.round(1)
    confidence = _num_series(out, "Confiance (%)")
    if RECO_MODE == "team":
        combined = 0.68 * score_team + 0.20 * score_trading + 0.12 * confidence
    elif RECO_MODE == "trading":
        combined = 0.25 * score_team + 0.63 * score_trading + 0.12 * confidence
    else:
        combined = 0.50 * score_team + 0.38 * score_trading + 0.12 * confidence

    is_foreigner = out["Étranger"].astype(str).str.contains("Étranger", case=False) if "Étranger" in out.columns else pd.Series(False, index=out.index)
    net_foreign = []
    for candidate_foreign, replaced_foreign in zip(is_foreigner.tolist(), replacement_foreign):
        net_foreign.append(int(bool(candidate_foreign)) - int(bool(replaced_foreign)))
    out["Impact étranger"] = net_foreign
    combined = combined - 4.0 * pd.Series(net_foreign, index=out.index).clip(lower=0)
    out["Score décision"] = combined.clip(0, 100).round(1)

    # Une ligue à plusieurs managers exige une offre réaliste, distincte du plafond absolu.
    target_margin = (RECO_MIN_MARGIN + (100 - confidence) / 1000.0).clip(lower=0.06, upper=0.20)
    team_premium = ((_num_series(out, "Score équipe") / 100.0) * 0.05).clip(0, 0.05)
    offers = _num_series(out, "Offres (#)").fillna(0).clip(lower=0)
    manager_pressure = min(1.0, max(0.0, (LEAGUE_MANAGERS - 1) / 8.0))
    competition_pct = (
        0.025
        + 0.020 * manager_pressure
        + 0.012 * offers.clip(upper=3)
        + 0.010 * (_num_series(out, "Score équipe") >= 75).astype(float)
    ).clip(upper=0.10)
    out["Prime concurrence (%)"] = (competition_pct * 100).round(1)
    out["Pression marché"] = pd.cut(
        competition_pct,
        bins=[-np.inf, 0.05, 0.075, np.inf],
        labels=["Normale", "Forte", "Très forte"],
    ).astype(str)

    def _ceil_bid(value):
        if pd.isna(value) or float(value) <= 0:
            return 0.0
        return float(np.ceil(float(value) / BID_INCREMENT) * BID_INCREMENT)

    competitive_bid = (price * (1.0 + competition_pct)).map(_ceil_bid)
    raw_ceiling = fair * (1.0 - target_margin + team_premium + competition_pct * 0.55)
    absolute_ceiling = pd.concat([raw_ceiling, competitive_bid], axis=1).max(axis=1)
    absolute_ceiling = pd.concat([absolute_ceiling, fair * 0.99], axis=1).min(axis=1).map(_ceil_bid)
    advised_bid = pd.concat([competitive_bid, absolute_ceiling], axis=1).min(axis=1).map(_ceil_bid)

    out["Offre conseillée"] = advised_bid
    out["Plafond absolu"] = absolute_ceiling
    # Alias conservé pour l'historique et les consommateurs existants.
    out["Enchère max"] = out["Plafond absolu"]

    decisions, reasons = [], []
    for idx, row in out.iterrows():
        p = float(row.get("Prix") or 0)
        max_bid = float(row.get("Enchère max") or 0) if pd.notna(row.get("Enchère max")) else 0
        gain_i = float(row.get("Gain pts/match") or 0)
        roi_i = float(row.get("ROI potentiel (%)") or 0) if pd.notna(row.get("ROI potentiel (%)")) else 0
        team_i = float(row.get("Score équipe") or 0)
        trade_i = float(row.get("Score trading") or 0)
        conf_i = float(row.get("Confiance (%)") or 0)
        decision_i = float(row.get("Score décision") or 0)
        affordable = p > 0 and max_bid > 0 and p <= max_bid
        if affordable and gain_i >= 1.0 and team_i >= 62 and conf_i >= 45:
            decisions.append("ACHETER")
            reasons.append(f"+{gain_i:.1f} pt/match vs {row.get('Remplace', 'effectif')} · offre {float(row.get('Offre conseillée') or p):,.0f}")
        elif affordable and roi_i >= 12 and trade_i >= 68 and conf_i >= 40:
            decisions.append("ACHETER / REVENDRE")
            reasons.append(f"ROI estimé {roi_i:.0f}% · offre {float(row.get('Offre conseillée') or p):,.0f}")
        elif affordable and decision_i >= 55:
            decisions.append("ENCHÉRIR")
            reasons.append(f"offre {float(row.get('Offre conseillée') or p):,.0f} · plafond {max_bid:,.0f}")
        elif max_bid > 0 and p > max_bid and (team_i >= 60 or trade_i >= 60):
            decisions.append("ATTENDRE")
            reasons.append(f"prix supérieur de {((p/max_bid)-1)*100:.0f}% au maximum conseillé")
        else:
            decisions.append("ÉVITER")
            reasons.append("gain ou confiance insuffisant")
    out["Décision"] = decisions
    out["Pourquoi"] = reasons
    return _round_metrics(out).sort_values(["Score décision", "Confiance (%)"], ascending=False)

def compute_roster_strategy(roster: pd.DataFrame, recommendations: pd.DataFrame) -> pd.DataFrame:
    """Transforme l'effectif de Droken en décisions garder/vendre/remplacer."""
    if roster is None or roster.empty:
        return pd.DataFrame()

    out = roster.copy()
    out["Projection pts"] = _projected_points(out)
    fair_input = out.copy()
    if "Valeur" in fair_input.columns and "Valeur marchée" not in fair_input.columns:
        fair_input["Valeur marchée"] = fair_input["Valeur"]
    out["Valeur estimée"] = _fair_value(fair_input)
    out["Confiance (%)"] = _confidence_score(out)
    projections = _num_series(out, "Projection pts")
    low_cut = float(projections.quantile(0.30)) if not projections.dropna().empty else 0.0

    actions, reasons, sell_prices = [], [], []
    replacements, replacement_bids, gains = [], [], []
    for _, row in out.iterrows():
        name = str(row.get("Joueur", ""))
        projection = float(row.get("Projection pts") or 0) if pd.notna(row.get("Projection pts")) else 0.0
        value = float(row.get("Valeur") or 0) if pd.notna(row.get("Valeur")) else 0.0
        fair_value = float(row.get("Valeur estimée") or value) if pd.notna(row.get("Valeur estimée")) else value
        momentum = float(row.get("Momentum 30 j (%)") or 0) if pd.notna(row.get("Momentum 30 j (%)")) else 0.0

        candidates = pd.DataFrame()
        if recommendations is not None and not recommendations.empty and "Remplace" in recommendations.columns:
            candidates = recommendations[recommendations["Remplace"].astype(str) == name].copy()
            candidates = candidates[candidates["Décision"].isin(["ACHETER", "ACHETER / REVENDRE", "ENCHÉRIR"])]
        if not candidates.empty:
            candidate = candidates.sort_values(["Gain pts/match", "Score décision"], ascending=False).iloc[0]
            candidate_gain = float(candidate.get("Gain pts/match") or 0)
            replacement = str(candidate.get("Joueur", "—"))
            replacement_bid = float(candidate.get("Offre conseillée") or candidate.get("Prix") or 0)
        else:
            candidate_gain, replacement, replacement_bid = 0.0, "—", 0.0

        overpriced = value > 0 and fair_value > 0 and value >= fair_value * 1.10
        weak = projection <= low_cut
        if candidate_gain >= 1.0:
            action = "REMPLACER"
            reason = f"{replacement} apporte +{candidate_gain:.1f} pt/match"
        elif weak and (overpriced or momentum < -5):
            action = "VENDRE"
            reason = "rendement faible et fenêtre de vente favorable"
        elif overpriced or momentum < -8:
            action = "ÉCOUTER OFFRES"
            reason = "valeur actuelle généreuse ou dynamique en baisse"
        else:
            action = "GARDER"
            reason = "aucun remplacement rentable identifié"

        sale_base = max(value, fair_value)
        sale_price = float(np.ceil((sale_base * (1.07 if action in ["VENDRE", "ÉCOUTER OFFRES"] else 1.12)) / BID_INCREMENT) * BID_INCREMENT) if sale_base > 0 else 0
        actions.append(action); reasons.append(reason); sell_prices.append(sale_price)
        replacements.append(replacement); replacement_bids.append(replacement_bid); gains.append(candidate_gain)

    out["Action"] = actions
    out["Pourquoi"] = reasons
    out["Prix vente conseillé"] = sell_prices
    out["Remplaçant conseillé"] = replacements
    out["Offre remplaçant"] = replacement_bids
    out["Gain remplacement"] = gains
    priority = {"REMPLACER": 0, "VENDRE": 1, "ÉCOUTER OFFRES": 2, "GARDER": 3}
    out["__priority"] = out["Action"].map(priority).fillna(9)
    return _round_metrics(out).sort_values(["__priority", "Projection pts"], ascending=[True, True]).drop(columns=["__priority"])

def optimize_action_plan(recommendations: pd.DataFrame, budget: float, max_actions: int = 5, foreign_capacity: int = 6):
    if recommendations is None or recommendations.empty:
        return pd.DataFrame(), 0
    eligible = recommendations[
        recommendations["Décision"].isin(["ACHETER", "ACHETER / REVENDRE", "ENCHÉRIR"])
    ].copy()
    eligible = eligible[_num_series(eligible, "Prix").fillna(0) > 0]
    if eligible.empty:
        return eligible, 0

    eligible["__utility"] = (
        _num_series(eligible, "Score décision")
        + _num_series(eligible, "Gain pts/match").clip(lower=0) * 8
        + _num_series(eligible, "ROI potentiel (%)").clip(lower=0, upper=50) * 0.25
    )
    pool = eligible.sort_values("__utility", ascending=False).head(18)
    best_indices, best_utility, best_cost = (), -1.0, 0.0
    for size in range(1, min(max_actions, len(pool)) + 1):
        for combo in itertools.combinations(pool.index.tolist(), size):
            chosen = pool.loc[list(combo)]
            cost_col = "Offre conseillée" if "Offre conseillée" in chosen.columns else "Prix"
            cost = float(_num_series(chosen, cost_col).sum())
            if cost > budget:
                continue
            replacements = [x for x in chosen["Remplace"].astype(str).tolist() if x and x != "Place libre"]
            if len(replacements) != len(set(replacements)):
                continue
            if _num_series(chosen, "Impact étranger").clip(lower=0).sum() > foreign_capacity:
                continue
            utility = float(_num_series(chosen, "__utility").sum())
            if utility > best_utility or (utility == best_utility and cost < best_cost):
                best_indices, best_utility, best_cost = combo, utility, cost
    if not best_indices:
        return pd.DataFrame(), 0
    selected = pool.loc[list(best_indices)].sort_values("Score décision", ascending=False).drop(columns=["__utility"])
    return _round_metrics(selected), int(best_cost)

def persist_recommendation_snapshot(plan: pd.DataFrame):
    if plan is None or plan.empty or not RECO_HISTORY_CSV:
        return
    try:
        snapshot = plan.copy()
        snapshot.insert(0, "Horodatage", dt.datetime.now().isoformat(timespec="seconds"))
        keep = [c for c in [
            "Horodatage", "Joueur", "Poste", "Prix", "Valeur estimée", "Enchère max",
            "Profit potentiel", "ROI potentiel (%)", "Gain pts/match", "Remplace",
            "Score équipe", "Score trading", "Confiance (%)", "Score décision", "Décision"
        ] if c in snapshot.columns]
        path = os.path.abspath(RECO_HISTORY_CSV)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            previous = pd.read_csv(path)
            snapshot = pd.concat([previous, snapshot[keep]], ignore_index=True).tail(10000)
        else:
            snapshot = snapshot[keep]
        snapshot.to_csv(path, index=False)
    except Exception as exc:
        print(f"[recommendations-v2] historique non écrit: {exc}")

# ----------------- OWNER / ROSTER ENRICHED -----------------
def fetch_team_meta(s, team_id: int):
    try:
        r = s.get(f"{BASE}/api/user/teams/{int(team_id)}", timeout=20)
        if r.status_code != 200:
            return None, None, ""
        j = r.json()
        d = j.get("data", j)
        if isinstance(d, list): d = d[0] if d else {}
        budget    = d.get("budget")
        teamvalue = d.get("teamvalue")
        uname     = _extract_username_from_payload(d)
        return budget, teamvalue, uname
    except Exception:
        return None, None, ""

def pos_family_label(p: object) -> str:
    """Normalise un poste TopScorers, y compris les valeurs absentes ou numériques."""
    if p is None:
        return "W"
    try:
        if pd.isna(p):
            return "W"
    except (TypeError, ValueError):
        pass

    value = str(p).strip().upper()
    if not value or value in {"NAN", "NONE", "<NA>"}:
        return "W"
    if value.startswith("G"):
        return "G"
    if value.startswith("D"):
        return "D"
    if value.startswith("C"):
        return "C"
    if "W" in value or "AIL" in value:
        return "W"
    return "W"

def build_my_enriched_roster(s, my_team_id: str, team_games_map: dict, team_ptsavg_map: dict) -> pd.DataFrame:
    if not my_team_id:
        return pd.DataFrame()
    try:
        tid = int(my_team_id)
    except:
        return pd.DataFrame()

    rows = []
    players = fetch_players_of_user_team(s, tid)
    for p in players:
        t = p.get("team") or {}
        pid = p.get("id")
        t_id = t.get("id")
        t_games = team_games_map.get(int(t_id)) if isinstance(t_id, int) else None
        t_pavg  = team_ptsavg_map.get(int(t_id)) if isinstance(t_id, int) else None

        cur_games = cur_avg = n1_games = n1_avg = n2_games = n2_avg = None
        mv90 = mvmax = mvmin = momentum = None
        try:
            if isinstance(pid, int):
                det = fetch_player_detail(s, pid)
                seas = parse_player_seasons(det)
                cur_games, cur_avg = seas["cur_games"], seas["cur_avg"]
                n1_games, n1_avg   = seas["n1_games"],  seas["n1_avg"]
                n2_games, n2_avg   = seas["n2_games"],  seas["n2_avg"]
                if ADD_PRICE_FEATURES:
                    s_hist = _parse_marketvalue_series(det)
                    mv90, mvmax, mvmin, momentum, _ = _price_features_from_series(s_hist)
                time.sleep(0.03)
        except Exception:
            pass

        rows.append({
            "ID": pid,
            "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
            "Poste": p.get("position_name"),
            "Équipe": t.get("acronym") or t.get("name") or "",
            "Points": p.get("points"),
            "Pts moy.": p.get("points_avg"),
            "Valeur": p.get("marketvalue"),
            "Étranger": "Étranger" if bool(p.get("is_foreigner")) else "",
            "Matchs (équipe)": t_games,
            "Matchs (saison)": cur_games,
            "Pts moy. (saison)": cur_avg,
            "Team PtsAvg": t_pavg,
            "Matchs N-1": n1_games,
            "Pts moy. N-1": n1_avg,
            "Matchs N-2": n2_games,
            "Pts moy. N-2": n2_avg,
            "MV 90 j": mv90,
            "MV min 365 j": mvmin,
            "MV max 365 j": mvmax,
            "Momentum 30 j (%)": momentum
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["Pts / 100k"] = _num_series(df, "Pts moy.") / (_num_series(df, "Valeur").replace(0, np.nan) / 100000)
    df = compute_alpha_score(df)
    return _round_metrics(df)

def build_owner_rosters(s, my_team_id: str, other_team_ids_env: str,
                        owner_overrides_env: str, team_games_map: dict, team_ptsavg_map: dict) -> pd.DataFrame:
    other_ids = _parse_ids_list(other_team_ids_env)
    owner_overrides = _parse_owner_name_overrides(owner_overrides_env)

    team_id_list = []
    if my_team_id:
        try: team_id_list.append(int(my_team_id))
        except: pass
    team_id_list.extend(other_ids)
    team_id_list = list(dict.fromkeys([x for x in team_id_list if isinstance(x, int)]))
    if not team_id_list:
        return pd.DataFrame()

    rows = []
    for tid in team_id_list:
        owner_label = fetch_team_username(s, tid) or owner_overrides.get(tid, f"Équipe {tid}")
        players = fetch_players_of_user_team(s, tid)
        for p in players:
            t = p.get("team") or {}
            pid = p.get("id")
            t_id = t.get("id")
            t_games = team_games_map.get(int(t_id)) if isinstance(t_id, int) else None
            t_pavg  = team_ptsavg_map.get(int(t_id)) if isinstance(t_id, int) else None

            cur_games = cur_avg = n1_games = n1_avg = n2_games = n2_avg = None
            mv90 = mvmax = mvmin = momentum = None
            try:
                if isinstance(pid, int):
                    det = fetch_player_detail(s, pid)
                    seas = parse_player_seasons(det)
                    cur_games, cur_avg = seas["cur_games"], seas["cur_avg"]
                    n1_games, n1_avg   = seas["n1_games"],  seas["n1_avg"]
                    n2_games, n2_avg   = seas["n2_games"],  seas["n2_avg"]
                    if ADD_PRICE_FEATURES:
                        s_hist = _parse_marketvalue_series(det)
                        mv90, mvmax, mvmin, momentum, _ = _price_features_from_series(s_hist)
                    time.sleep(0.035)
            except Exception:
                pass

            rows.append({
                "ID": pid,
                "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
                "Poste": p.get("position_name"),
                "Équipe": t.get("acronym") or t.get("name") or "",
                "Propriétaire": owner_label,
                "Points": p.get("points"),
                "Pts moy.": p.get("points_avg"),
                "Valeur": p.get("marketvalue"),
                "Étranger": "Étranger" if bool(p.get("is_foreigner")) else "",
                "Matchs (équipe)": t_games,
                "Matchs (saison)": cur_games,
                "Pts moy. (saison)": cur_avg,
                "Team PtsAvg": t_pavg,
                "Matchs N-1": n1_games,
                "Pts moy. N-1": n1_avg,
                "Matchs N-2": n2_games,
                "Pts moy. N-2": n2_avg,
                "MV 90 j": mv90,
                "MV min 365 j": mvmin,
                "MV max 365 j": mvmax,
                "Momentum 30 j (%)": momentum
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["Pts / 100k"] = _num_series(df, "Pts moy.") / (_num_series(df, "Valeur").replace(0, np.nan) / 100000)
    df["Décote (%)"] = pd.Series([np.nan]*len(df), index=df.index)
    df = compute_alpha_score(df)

    if "Propriétaire" in df.columns:
        df["Propriétaire"] = df["Propriétaire"].astype(str).str.replace(r"<.*?>", "", regex=True).str.strip()
    if "Étranger" in df.columns:
        df["Étranger"] = df["Étranger"].astype(str).str.contains("Étranger", case=False).map(lambda b: "Étranger" if b else "")

    df = _round_metrics(df)
    keep_cols = [c for c in [
        "Joueur","Poste","Équipe","Propriétaire","Étranger",
        "Points","Pts moy.","Valeur","Pts / 100k",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "Matchs N-1","Pts moy. N-1","Matchs N-2","Pts moy. N-2",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)",
        "AlphaScore"
    ] if c in df.columns]
    return df[keep_cols]

# ----------------- ALL PLAYERS -----------------
def fetch_all_players_by_teams(s, team_ids: list, fetch_details: bool,
                               df_effectif: pd.DataFrame,
                               owners_index: dict,
                               team_games: dict,
                               team_ptsavg: dict) -> pd.DataFrame:
    rows = []
    my_ids = set()
    if df_effectif is not None and not df_effectif.empty and "ID" in df_effectif.columns:
        try:
            my_ids = set(pd.to_numeric(df_effectif["ID"], errors="coerce").dropna().astype(int).tolist())
        except Exception:
            my_ids = set()

    for tid in team_ids:
        players = fetch_team_roster(s, tid)
        for p in players:
            t = p.get("team") or {}
            pid = p.get("id")
            is_foreigner = bool(p.get("is_foreigner"))
            owner = owners_index.get(pid, "Moi" if (isinstance(pid,int) and pid in my_ids) else "")
            t_id = t.get("id")
            t_games = team_games.get(int(t_id), None) if isinstance(t_id,int) else None
            t_pavg  = team_ptsavg.get(int(t_id), None) if isinstance(t_id,int) else None

            cur_games = cur_avg = n1_games = n1_avg = n2_games = n2_avg = None
            mv90 = mvmax = mvmin = momentum = None
            spark = ""
            if fetch_details and isinstance(pid, int):
                try:
                    detail = fetch_player_detail(s, int(pid))
                    seas = parse_player_seasons(detail)
                    cur_games, cur_avg = seas["cur_games"], seas["cur_avg"]
                    n1_games, n1_avg   = seas["n1_games"],  seas["n1_avg"]
                    n2_games, n2_avg   = seas["n2_games"],  seas["n2_avg"]
                    if ADD_PRICE_FEATURES:
                        s_hist = _parse_marketvalue_series(detail)
                        mv90, mvmax, mvmin, momentum, spark = _price_features_from_series(s_hist)
                except Exception:
                    pass
                time.sleep(0.04)

            rows.append({
                "ID": pid,
                "Joueur": f"{p.get('firstname','')} {p.get('lastname','')}".strip(),
                "Poste": p.get("position_name"),
                "Équipe": t.get("acronym") or t.get("name") or "",
                "Points": p.get("points"),
                "Pts moy.": p.get("points_avg"),
                "Valeur": p.get("marketvalue"),
                "Étranger": "Étranger" if is_foreigner else "",
                "Propriétaire": owner,
                "Matchs (équipe)": t_games,
                "Matchs (saison)": cur_games,
                "Pts moy. (saison)": cur_avg,
                "Team PtsAvg": t_pavg,
                "Matchs N-1": n1_games,
                "Pts moy. N-1": n1_avg,
                "Matchs N-2": n2_games,
                "Pts moy. N-2": n2_avg,
                "MV 90 j": mv90,
                "MV min 365 j": mvmin,
                "MV max 365 j": mvmax,
                "Momentum 30 j (%)": momentum,
                "MV Spark": spark,
            })
        time.sleep(0.05)

    df = pd.DataFrame(rows).drop_duplicates(subset=["ID"])
    if not df.empty:
        pts_avg = _num_series(df, "Pts moy.")
        mv      = _num_series(df, "Valeur")
        df["Pts / 100k"] = pts_avg / (mv.replace(0, np.nan) / 100000)
        df["Décote (%)"] = pd.Series([np.nan]*len(df), index=df.index, dtype="float64")
    return df

# ----------------- UI HELPERS -----------------
def reorder_columns(df: pd.DataFrame, desired_order: list) -> pd.DataFrame:
    if df is None or df.empty: return df
    cols = [c for c in desired_order if c in df.columns]
    rest = [c for c in df.columns if c not in cols]
    return df[cols + rest]

# ----------------- MAIN -----------------
def main():
    s = login_session()

    # Marché enrichi
    df_sales_display, _df_market_calc = fetch_market_enriched(s)
    print("VENTES (affichage):", df_sales_display.shape, " | CALC:", _df_market_calc.shape)

    # Mon équipe
    df_effectif, df_lineup, my_username = fetch_my_team_views(s)
    print("TEAM:", df_effectif.shape, df_lineup.shape, "| me:", my_username or "-")

    # Budget / meta team
    budget_live, teamvalue_live, uname_live = fetch_team_meta(s, int(TEAM_ID) if TEAM_ID else 506387)
    print("TEAM META:", "budget=", budget_live, "teamvalue=", teamvalue_live, "owner=", uname_live or "-")

    # Owners index
    other_team_ids  = _parse_ids_list(OTHER_TEAM_IDS_ENV)
    owner_overrides = _parse_owner_name_overrides(OTHER_TEAM_NAMES_ENV)
    owners_index = build_owners_index(s, df_effectif, other_team_ids, owner_overrides, my_username)
    print("OWNERS index:", len(owners_index))

    # Rankings
    team_games_map, _, team_ptsavg_map = fetch_rankings_maps(s)

    # Effectif enrichi utilisé par le moteur V2 pour calculer le vrai gain de remplacement.
    df_my_enriched = build_my_enriched_roster(s, TEAM_ID or "506387", team_games_map, team_ptsavg_map)
    df_my_enriched = reorder_columns(df_my_enriched, [
        "Joueur","Poste","Équipe","Étranger",
        "Points","Pts moy.","Valeur","Pts / 100k",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "Matchs N-1","Pts moy. N-1","Matchs N-2","Pts moy. N-2",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)","AlphaScore"
    ])

    # Tous les joueurs
    team_ids = _parse_team_ids_env(ALL_PLAYERS_TEAMS_ENV, DEFAULT_TEAMS)
    df_all_players = fetch_all_players_by_teams(
        s, team_ids, ALL_PLAYERS_FETCH_DETAILS, df_effectif, owners_index, team_games_map, team_ptsavg_map
    )
    df_all_players_scored = compute_alpha_score(df_all_players.copy()) if not df_all_players.empty else df_all_players
    df_all_players_scored = reorder_columns(df_all_players_scored, [
        "Joueur","Poste","Équipe","Propriétaire","Étranger",
        "Points","Pts moy.","Valeur","Pts / 100k",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)","MV Spark","AlphaScore"
    ])
    df_all_players_scored = _round_metrics(df_all_players_scored)
    print("ALL PLAYERS:", df_all_players_scored.shape, "| teams:", len(team_ids))

    # Ventes → AlphaScore
    df_sales_for_view = compute_alpha_score(df_sales_display.copy()) if not df_sales_display.empty else df_sales_display
    df_sales_for_view = reorder_columns(df_sales_for_view, [
        "Joueur","Poste","Équipe","Prix","Valeur marchée","Décote (%)","Pts / 100k","Pts moy.",
        "Matchs (équipe)","Matchs (saison)","Pts moy. (saison)","Team PtsAvg",
        "MV 90 j","MV min 365 j","MV max 365 j","Momentum 30 j (%)","Décote vs max 365 (%)","MV Spark",
        "Vendeur","Offres (#)","Expire dans (s)","AlphaScore"
    ])
    df_sales_for_view = _round_metrics(df_sales_for_view)

    # Seuil dynamique AlphaScore
    if not df_sales_for_view.empty and "AlphaScore" in df_sales_for_view.columns:
        sseries = pd.to_numeric(df_sales_for_view["AlphaScore"], errors="coerce").dropna()
        if len(sseries) >= 3:
            top = float(sseries.max())
            q85 = float(sseries.quantile(0.85))
            mu, sigma = float(sseries.mean()), float(sseries.std(ddof=0))
            band = mu + 0.6 * sigma
            base = max(q85, band)
            dyn_threshold = min(base, top - 1.0) if top > 47 else top * 0.98
            dyn_threshold = max(45.0, round(dyn_threshold, 1))
        else:
            dyn_threshold = max(45.0, float(MUST_BUY_THRESHOLD_FALLBACK))
    else:
        dyn_threshold = max(45.0, float(MUST_BUY_THRESHOLD_FALLBACK))

    # Recommandations V2 : budget réel, remplacement dans l'effectif, trading et confiance.
    budget_available = int(budget_live) if budget_live is not None and float(budget_live) > 0 else RECO_BUDGET
    df_reco = compute_recommendations_v2(df_sales_for_view.copy(), df_my_enriched.copy()) if not df_sales_for_view.empty else pd.DataFrame()
    current_foreign = int(df_my_enriched["Étranger"].astype(str).str.contains("Étranger", case=False).sum()) if "Étranger" in df_my_enriched.columns else 0
    foreign_capacity = max(0, 6 - current_foreign)
    df_action_plan, total_cost = optimize_action_plan(df_reco, budget_available, RECO_MAX_ACTIONS, foreign_capacity)
    persist_recommendation_snapshot(df_action_plan)
    df_roster_strategy = compute_roster_strategy(df_my_enriched.copy(), df_reco.copy())

    decision_columns = [
        "Décision", "Joueur", "Poste", "Équipe", "Prix", "Offre conseillée", "Plafond absolu", "Pression marché", "Valeur estimée",
        "Profit potentiel", "ROI potentiel (%)", "Projection pts", "Remplace", "Gain pts/match",
        "Score équipe", "Score trading", "Confiance (%)", "Score décision", "Pourquoi",
        "Étranger", "Impact étranger", "Expire dans (s)", "AlphaScore"
    ]
    if not df_reco.empty:
        df_reco = reorder_columns(df_reco, decision_columns)
    if not df_action_plan.empty:
        df_action_plan = reorder_columns(df_action_plan, decision_columns)

    # Équipe (par propriétaire)
    df_team_by_owner = build_owner_rosters(
        s, TEAM_ID, OTHER_TEAM_IDS_ENV, OTHER_TEAM_NAMES_ENV, team_games_map, team_ptsavg_map
    )

    # ---------- Sections ----------
    sections = []

    sections.append({
        "id": "tabLive",
        "title": "Live",
        "content": """
<div id="liveRoot">
  <div class="row g-3 mb-3">
    <div class="col-12 col-md-4"><div class="card p-3 h-100"><div class="small text-secondary">État</div><div id="liveStatus" class="h5 m-0">Connexion…</div></div></div>
    <div class="col-6 col-md-4"><div class="card p-3 h-100"><div class="small text-secondary">Points Droken</div><div id="livePoints" class="h3 m-0">—</div></div></div>
    <div class="col-6 col-md-4"><div class="card p-3 h-100"><div class="small text-secondary">Rang live</div><div id="liveRank" class="h3 m-0">—</div></div></div>
  </div>
  <div id="liveMessage" class="alert alert-secondary py-2">Chargement des données TopScorers…</div>
  <div class="card p-3 mb-3">
    <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-2">
      <div><h2 class="h5 mb-0">Joueurs de Droken</h2><div class="small text-secondary">Les points sont calculés par TopScorers à partir des 42 événements officiels.</div></div>
      <button id="liveRefresh" class="btn btn-sm btn-outline-light" type="button">Actualiser</button>
    </div>
    <div class="table-wrapper">
      <table class="table table-sm align-middle mb-0">
        <thead><tr><th>Joueur</th><th>Équipe</th><th>État</th><th>Pts live</th><th>Buts</th><th>Assists</th><th>Tirs</th><th>Blocs</th><th>Pén.</th><th>Arrêts</th><th>+/-</th></tr></thead>
        <tbody id="livePlayers"><tr><td colspan="11" class="text-secondary">Chargement…</td></tr></tbody>
      </table>
    </div>
  </div>
  <div class="card p-3">
    <h2 class="h5 mb-2">Matchs</h2>
    <div id="liveGames" class="text-secondary">Aucun match chargé.</div>
  </div>
  <div class="small text-secondary mt-2">Actualisation toutes les 30 s pendant les matchs, toutes les 5 min sinon. Le dernier résultat reste visible si l’API est indisponible.</div>
</div>
""",
        "script": r"""
<script>
(() => {
  const root = document.getElementById("liveRoot");
  if (!root) return;
  let timer = null;
  let loading = false;
  const esc = value => String(value ?? "—").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const number = value => value === null || value === undefined ? "—" : Number(value).toLocaleString("fr-FR", {maximumFractionDigits:1});
  const stat = (player, key) => number(player.stats && player.stats[key]);

  function liveApiUrl() {
    const origins = [];
    try {
      if (window.parent && window.parent !== window && /^https?:$/.test(window.parent.location.protocol)) {
        origins.push(window.parent.location.origin);
      }
    } catch (_) {}
    try {
      if (window.top && window.top !== window && /^https?:$/.test(window.top.location.protocol)) {
        origins.push(window.top.location.origin);
      }
    } catch (_) {}
    try {
      if (document.referrer) origins.push(new URL(document.referrer).origin);
    } catch (_) {}
    try {
      if (/^https?:$/.test(window.location.protocol)) origins.push(window.location.origin);
    } catch (_) {}
    const origin = origins.find(value => value && value !== "null");
    if (!origin) throw new Error("origine publique introuvable");
    return new URL("/api/live", origin).href;
  }

  function schedule(ms) {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => refresh(false), ms);
  }

  function render(data) {
    const status = document.getElementById("liveStatus");
    const points = document.getElementById("livePoints");
    const rank = document.getElementById("liveRank");
    const message = document.getElementById("liveMessage");
    status.textContent = data.status === "LIVE" ? "● EN DIRECT" :
      data.status === "MEMBER_REQUIRED" ? "MEMBER REQUIS" :
      data.status === "ERROR" ? "INDISPONIBLE" : "HORS MATCH";
    status.className = "h5 m-0 " + (data.status === "LIVE" ? "text-success" : data.status === "ERROR" ? "text-danger" : "");
    points.textContent = number(data.live_points);
    rank.textContent = data.rank ? "#" + esc(data.rank) : "—";
    message.textContent = data.message || "";
    message.className = "alert py-2 " + (data.status === "LIVE" ? "alert-success" : data.status === "ERROR" ? "alert-danger" : "alert-secondary");

    const players = Array.isArray(data.players) ? data.players : [];
    document.getElementById("livePlayers").innerHTML = players.length ? players.map(player => {
      const state = player.playing ? "Sur la glace" : player.lined_up ? "Aligné" : "Banc";
      return "<tr>" +
        "<td><strong>" + esc(player.name) + "</strong><div class='small text-secondary'>" + esc(player.position) + "</div></td>" +
        "<td>" + esc(player.team) + "</td><td>" + esc(state) + "</td>" +
        "<td><strong>" + number(player.live_points) + "</strong></td>" +
        "<td>" + stat(player,"goals") + "</td><td>" + stat(player,"assists") + "</td>" +
        "<td>" + stat(player,"shots_on_goal") + "</td><td>" + stat(player,"blocked_shots") + "</td>" +
        "<td>" + stat(player,"penalty_minutes") + "</td><td>" + stat(player,"saves") + "</td>" +
        "<td>" + stat(player,"plus_minus") + "</td></tr>";
    }).join("") : "<tr><td colspan='11' class='text-secondary'>Aucune donnée joueur disponible.</td></tr>";

    const games = Array.isArray(data.games) ? data.games : [];
    document.getElementById("liveGames").innerHTML = games.length ? games.map(game =>
      "<div class='d-flex justify-content-between border-bottom py-2 gap-3'>" +
      "<span>" + esc(game.home) + " — " + esc(game.away) + "</span>" +
      "<strong>" + esc(game.home_score) + " : " + esc(game.away_score) + "</strong>" +
      "<span class='small text-secondary'>" + esc(game.status) + "</span></div>"
    ).join("") : "<span class='text-secondary'>Aucun match en cours ou programmé dans la réponse TopScorers.</span>";

    const stamp = data.updated_at ? new Date(data.updated_at).toLocaleTimeString("fr-FR") : "—";
    document.getElementById("liveRefresh").textContent = "Actualisé " + stamp;
  }

  async function refresh(force) {
    const pane = document.getElementById("tabLive");
    if (!force && (document.hidden || !pane || !pane.classList.contains("active"))) {
      schedule(60000);
      return;
    }
    if (loading) return;
    loading = true;
    try {
      const response = await fetch(liveApiUrl(), {cache:"no-store", credentials:"same-origin"});
      const data = await response.json();
      render(data);
      schedule(data.status === "LIVE" ? 30000 : 300000);
    } catch (error) {
      render({status:"ERROR", message:"Live inaccessible : " + error, players:[], games:[]});
      schedule(60000);
    } finally {
      loading = false;
    }
  }

  document.getElementById("liveRefresh").addEventListener("click", () => refresh(true));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
  document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => tab.addEventListener("shown.bs.tab", event => {
    if (event.target && event.target.getAttribute("data-bs-target") === "#tabLive") refresh(true);
  }));
  refresh(true);
})();
</script>
"""
    })

    lineup_missing = 0
    if df_lineup is not None and not df_lineup.empty and "Actuel" in df_lineup.columns:
        current_slots = df_lineup["Actuel"].astype(str).str.strip().str.lower()
        lineup_missing = int(current_slots.isin(["", "none", "nan", "null"]).sum())
    lineup_penalty = lineup_missing * 50
    lineup_state = (
        "<div class='alert alert-success py-2 mb-3'>Composition complète : aucune pénalité de place vide détectée.</div>"
        if lineup_missing == 0
        else f"<div class='alert alert-danger py-2 mb-3'><b>{lineup_missing} place(s) vide(s)</b> : risque de -{lineup_penalty} points au prochain match.</div>"
    )
    sections.append({
        "id": "tabLineup",
        "title": "Compo",
        "content": f"""
<div class="row g-3 mb-3">
  <div class="col-6"><div class="card p-3 h-100"><div class="small text-secondary">Places vides</div><div class="h3 m-0">{lineup_missing}</div></div></div>
  <div class="col-6"><div class="card p-3 h-100"><div class="small text-secondary">Pénalité potentielle</div><div class="h3 m-0 text-danger">-{lineup_penalty}</div></div></div>
</div>
{lineup_state}
<div class="card p-3">
  <h2 class="h5 mb-1">Composition actuelle de Droken</h2>
  <div class="small text-secondary mb-2">À vérifier avant le début du premier match : la composition devient ensuite verrouillée.</div>
  {df_to_html_table(df_lineup, "tblLineup", "Chercher un joueur ou un slot…") if df_lineup is not None and not df_lineup.empty else "<div class='text-secondary'>Composition indisponible dans la réponse TopScorers.</div>"}
</div>"""
    })

    if not df_action_plan.empty:
        total_gain = float(_num_series(df_action_plan, "Gain pts/match").clip(lower=0).sum())
        total_profit = float(_num_series(df_action_plan, "Profit potentiel").fillna(0).sum())
        avg_confidence = float(_num_series(df_action_plan, "Confiance (%)").fillna(0).mean())
        plan_summary = f"""
<div class="row g-3 mb-3">
  <div class="col-6 col-xl-3"><div class="card p-3 h-100"><div class="small text-secondary">Budget disponible</div><div class="h4 m-0">{budget_available:,.0f}</div></div></div>
  <div class="col-6 col-xl-3"><div class="card p-3 h-100"><div class="small text-secondary">Coût du plan</div><div class="h4 m-0">{total_cost:,.0f}</div></div></div>
  <div class="col-6 col-xl-3"><div class="card p-3 h-100"><div class="small text-secondary">Gain estimé</div><div class="h4 m-0 text-success">+{total_gain:.1f} pts/match</div></div></div>
  <div class="col-6 col-xl-3"><div class="card p-3 h-100"><div class="small text-secondary">Confiance moyenne</div><div class="h4 m-0">{avg_confidence:.0f}%</div></div></div>
</div>"""
        sections.append({
            "id":"tabActionPlan", "title":"Maintenant",
            "content": f"""
{plan_summary}
<div class="card p-3">
  <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-2">
    <div><h2 class="h5 mb-1">Les décisions à prendre maintenant</h2><div class="small text-secondary">Mode {RECO_MODE} · combinaison optimisée sous le budget réel · maximum {RECO_MAX_ACTIONS} actions.</div></div>
    <span class="badge rounded-pill text-bg-success">V2 active</span>
  </div>
  {df_to_html_table(df_action_plan, "tblActionPlan", "Filtrer le plan d’action…")}
</div>"""
        })
    else:
        sections.append({
            "id":"tabActionPlan", "title":"Plan d’action",
            "content":"<div class='card p-4'><h2 class='h5'>Aucune action immédiate</h2><div class='text-secondary'>Le moteur V2 ne trouve actuellement aucune opportunité suffisamment intéressante et abordable. Attendre est ici une décision volontaire.</div></div>"
        })

    roster_columns = [
        "Action", "Joueur", "Poste", "Projection pts", "Valeur", "Valeur estimée",
        "Prix vente conseillé", "Remplaçant conseillé", "Offre remplaçant",
        "Gain remplacement", "Confiance (%)", "Pourquoi"
    ]
    df_roster_view = reorder_columns(df_roster_strategy, roster_columns) if not df_roster_strategy.empty else pd.DataFrame()
    df_sell_view = df_roster_view[df_roster_view["Action"].isin(["REMPLACER", "VENDRE", "ÉCOUTER OFFRES"])].copy() if not df_roster_view.empty else pd.DataFrame()

    sections.append({
        "id":"tabMyTeam", "title":"Mon équipe",
        "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-1">Effectif de Droken</h2>
  <div class="small text-secondary mb-2">Une décision simple par joueur : garder, écouter les offres, vendre ou remplacer.</div>
  {df_to_html_table(df_roster_view, "tblMyTeam", "Chercher dans mon équipe…")}
</div>"""
    })
    sections.append({
        "id":"tabSell", "title":"À vendre",
        "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-1">Ventes et remplacements prioritaires</h2>
  <div class="small text-secondary mb-2">Le prix conseillé laisse une marge de négociation adaptée à une ligue de {LEAGUE_MANAGERS} managers.</div>
  {df_to_html_table(df_sell_view, "tblSell", "Filtrer les ventes…") if not df_sell_view.empty else "<div class='text-secondary'>Aucune vente urgente : ton effectif peut être conservé.</div>"}
</div>"""
    })

    sections.append({
        "id":"tabVentes", "title":"Marché",
        "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-2">Ventes du marché</h2>
  <div class="small text-secondary mb-2">Lignes surlignées en <b>vert</b> = AlphaScore ≥ {dyn_threshold:.0f} (seuil dynamique).</div>
  {df_to_html_table(df_sales_for_view, "tblVentes", "Filtrer les ventes…")}
</div>"""
    })

    if not df_reco.empty:
        sections.append({
            "id":"tabRecos", "title":"Achats",
            "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-2">Toutes les recommandations V2</h2>
  <div class="small text-secondary mb-2">Chaque vente reçoit une décision, une enchère maximale, un gain sportif, un potentiel trading et un niveau de confiance.</div>
  {df_to_html_table(df_reco, "tblRecos", "Filtrer les recos…")}
</div>"""
        })
    else:
        sections.append({"id":"tabRecos","title":"Achats","content":"<div class='text-secondary'>Aucune recommandation.</div>"})

    if not df_all_players_scored.empty:
        note = f"<div class='small text-secondary mb-2'>Équipes interrogées : {', '.join(map(str, team_ids))}. Détails joueur : {'ON' if ALL_PLAYERS_FETCH_DETAILS else 'OFF'}.</div>"
        sections.append({
            "id":"tabAllPlayers","title":"Joueurs",
            "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-2">Tous les joueurs (par équipes)</h2>
  {note}
  {df_to_html_table(sanitize_for_html(df_all_players_scored), "tblAllPlayers", "Filtrer tous les joueurs…")}
</div>"""
        })
    else:
        sections.append({"id":"tabAllPlayers","title":"Joueurs","content":"<div class='text-secondary'>Aucun joueur récupéré (vérifie la liste d’IDs d’équipes).</div>"})

    if df_team_by_owner is not None and not df_team_by_owner.empty:
        owners_list = sorted(set(df_team_by_owner["Propriétaire"].astype(str).str.strip()))
        teams_list  = sorted(set(df_team_by_owner["Équipe"].astype(str).str.strip()))
        team_table_html = df_to_html_table(df_team_by_owner, "tblOwners", "Rechercher…")
        owner_opts = "<option value='__ALL__' selected>Tous</option>" + "".join(f"<option value='{o}'>{o}</option>" for o in owners_list)
        team_opts  = "<option value='__ALL__' selected>Toutes</option>" + "".join(f"<option value='{t}'>{t}</option>" for t in teams_list)

        sections.append({
            "id":"tabOwners","title":"Ligue",
            "content": f"""
<div class="card p-3">
  <h2 class="h5 mb-3">Équipes par propriétaire</h2>

  <div class="row g-2 align-items-end mb-3">
    <div class="col-sm-6 col-md-4">
      <label class="form-label small text-secondary">Propriétaire</label>
      <select id="ownerSelect" class="form-select form-select-sm">{owner_opts}</select>
    </div>
    <div class="col-sm-6 col-md-4">
      <label class="form-label small text-secondary">Équipe (club)</label>
      <select id="teamSelect" class="form-select form-select-sm">{team_opts}</select>
    </div>
  </div>

  <div id="ownerSummary" class="row g-3 mb-3">
    <div class="col-12 text-secondary">Utilise les filtres ci-dessus pour voir les stats détaillées.</div>
  </div>

  <div class="card p-3 mb-3">
    <h3 class="h6 mb-2">Top 5 joueurs (par AlphaScore)</h3>
    <div id="ownerTop5Table" class="text-secondary">—</div>
  </div>

  {team_table_html}
</div>""",
            "script": """
  <script>
document.addEventListener('DOMContentLoaded', function () {
  function colIndex(tbl, namePart) {
    if (tbl.tHead && tbl.tHead.rows.length) {
      var ths = tbl.tHead.rows[0].cells;
      for (var i=0;i<ths.length;i++) {
        var t = (ths[i].innerText || '').trim().toLowerCase();
        if (t.indexOf(namePart.toLowerCase()) >= 0) return i;
      }
    }
    return -1;
  }

  var ownerSel = document.getElementById('ownerSelect');
  var teamSel  = document.getElementById('teamSelect');
  var tbl      = document.getElementById('tblOwners');
  var summary  = document.getElementById('ownerSummary');
  var top5Div  = document.getElementById('ownerTop5Table');
  if (!ownerSel || !teamSel || !tbl || !tbl.tBodies || !tbl.tBodies[0]) return;

  window.idxOwner   = colIndex(tbl, 'propriétaire');
  window.idxPoste   = colIndex(tbl, 'poste');
  window.idxTeam    = colIndex(tbl, 'équipe');
  window.idxValeur  = colIndex(tbl, 'valeur');
  window.idxPtsMoy  = colIndex(tbl, 'pts moy');
  window.idxPts100k = colIndex(tbl, 'pts / 100k');
  window.idxAlpha   = colIndex(tbl, 'alphascore');
  window.idxEtr     = colIndex(tbl, 'étranger');
  window.idxJoueur  = colIndex(tbl, 'joueur');

  var ownerTeamCtl = applyOwnerTeamFilters('ownerSelect','teamSelect','tblOwners','ownerSummary','ownerTop5Table');

  function refresh() { ownerTeamCtl.refresh(); }

  ownerSel.addEventListener('change', refresh);
  teamSel.addEventListener('change', refresh);
  refresh();
});
</script>

"""
        })
    else:
        sections.append({"id":"tabOwners","title":"Ligue","content":"<div class='text-secondary'>Aucune équipe trouvée (vérifie TEAM_ID et OTHER_TEAM_IDS).</div>"})

    legend_html = f"""
<div class="row g-3 mb-3">
  <div class="col-12 col-lg-7">
    <div class="card p-4 h-100">
      <div class="small text-uppercase text-secondary mb-1">Mode d’emploi</div>
      <h2 class="h4 mb-2">Comment utiliser le dashboard</h2>
      <p class="text-secondary mb-0">Commence par <b>Live</b> les soirs de match, <b>Compo</b> avant le coup d’envoi, puis <b>Maintenant</b> pour les décisions de marché. Les autres onglets servent à approfondir.</p>
    </div>
  </div>
  <div class="col-12 col-lg-5">
    <div class="card p-4 h-100">
      <div class="small text-secondary">Configuration actuelle</div>
      <div class="h5 mb-1">{LEAGUE_MANAGERS} managers · mode {RECO_MODE}</div>
      <div class="small text-secondary">Dashboard complet toutes les 30 min · Live 30 s en match / 5 min hors match.</div>
    </div>
  </div>
</div>

<div class="card p-3 mb-3">
  <h3 class="h5 mb-3">Les onglets</h3>
  <div class="table-wrapper">
    <table class="table table-sm align-middle mb-0">
      <thead><tr><th>Onglet</th><th>À quoi il sert</th><th>Quand le consulter</th></tr></thead>
      <tbody>
        <tr><td><b>Live</b></td><td>Points de Droken, joueurs alignés, événements et matchs.</td><td>Pendant les rencontres.</td></tr>
        <tr><td><b>Compo</b></td><td>Contrôle les slots et calcule la pénalité potentielle des places vides.</td><td>Avant le premier match.</td></tr>
        <tr><td><b>Maintenant</b></td><td>Plan d’achats optimisé selon ton budget réel.</td><td>À chaque nouvelle vente.</td></tr>
        <tr><td><b>Mon équipe</b></td><td>Décision garder, vendre, écouter ou remplacer pour chaque joueur.</td><td>Pour gérer l’effectif.</td></tr>
        <tr><td><b>À vendre</b></td><td>Joueurs dont la vente ou le remplacement est prioritaire.</td><td>Quand tu dois libérer du budget.</td></tr>
        <tr><td><b>Marché</b></td><td>Toutes les ventes et leurs données brutes.</td><td>Pour vérifier une opportunité.</td></tr>
        <tr><td><b>Achats</b></td><td>Classement complet du moteur V3.</td><td>Pour comparer plusieurs cibles.</td></tr>
        <tr><td><b>Joueurs</b></td><td>Base générale des joueurs analysés.</td><td>Pour le scouting.</td></tr>
        <tr><td><b>Ligue</b></td><td>Effectifs des autres managers et filtres par club/propriétaire.</td><td>Pour anticiper la concurrence.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<div class="row g-3 mb-3">
  <div class="col-12 col-xl-6">
    <div class="card p-3 h-100">
      <h3 class="h5">Comprendre une enchère</h3>
      <ul class="mb-0">
        <li><b>Prix</b> : montant actuellement affiché par TopScorers.</li>
        <li><b>Offre conseillée</b> : montant réaliste pour gagner face aux {LEAGUE_MANAGERS - 1} autres managers.</li>
        <li><b>Plafond absolu</b> : limite à ne pas dépasser, même en cas de surenchère.</li>
        <li><b>Pression marché</b> : concurrence estimée selon la ligue, les offres et l’intérêt sportif.</li>
        <li><b>Valeur estimée</b> : valeur juste calculée avec le marché actuel et l’historique.</li>
      </ul>
    </div>
  </div>
  <div class="col-12 col-xl-6">
    <div class="card p-3 h-100">
      <h3 class="h5">Décisions sur l’effectif</h3>
      <ul class="mb-0">
        <li><b>GARDER</b> : aucun remplacement suffisamment rentable.</li>
        <li><b>ÉCOUTER OFFRES</b> : vendre seulement si une offre généreuse arrive.</li>
        <li><b>VENDRE</b> : rendement faible ou fenêtre de prix favorable.</li>
        <li><b>REMPLACER</b> : une cible disponible apporte un gain sportif significatif.</li>
        <li><b>Prix vente conseillé</b> : prix de départ laissant une marge de négociation.</li>
      </ul>
    </div>
  </div>
</div>

<div class="row g-3 mb-3">
  <div class="col-12 col-xl-6">
    <div class="card p-3 h-100">
      <h3 class="h5">Scores du moteur</h3>
      <ul class="mb-0">
        <li><b>Projection pts</b> : moyenne pondérée de la saison, N-1 et N-2.</li>
        <li><b>Gain pts/match</b> : projection de la cible moins celle du joueur remplacé.</li>
        <li><b>Score équipe</b> : intérêt sportif pour Droken.</li>
        <li><b>Score trading</b> : potentiel de plus-value.</li>
        <li><b>Confiance</b> : quantité et solidité des données disponibles.</li>
        <li><b>Score décision</b> : synthèse utilisée pour le plan d’action.</li>
      </ul>
    </div>
  </div>
  <div class="col-12 col-xl-6">
    <div class="card p-3 h-100">
      <h3 class="h5">Marché et historique</h3>
      <ul class="mb-0">
        <li><b>MV 90 j</b> : valeur moyenne récente.</li>
        <li><b>MV min/max 365 j</b> : fourchette historique disponible.</li>
        <li><b>Momentum 30 j</b> : direction récente de la valeur.</li>
        <li><b>Décote</b> : différence entre le prix demandé et une référence de marché.</li>
        <li><b>ROI potentiel</b> : plus-value théorique avant concurrence.</li>
        <li><b>AlphaScore</b> : indicateur historique d’opportunité, secondaire face au Score décision.</li>
      </ul>
    </div>
  </div>
</div>

<div class="card p-3 mb-3">
  <h3 class="h5">Live et calcul des points</h3>
  <p>La moyenne officielle TopScorers intègre déjà les 42 événements : buts, assists, tirs, blocs, engagements, pénalités, temps de glace, résultats et statistiques des gardiens. Le dashboard utilise ce total pour éviter tout double comptage et affiche le détail disponible pour expliquer le score.</p>
  <ul class="mb-0">
    <li><b>EN DIRECT</b> : au moins un match ou joueur est signalé en cours.</li>
    <li><b>HORS MATCH</b> : dernière information disponible, sans rencontre active.</li>
    <li><b>MEMBER REQUIS</b> : TopScorers réserve la donnée demandée à l’abonnement.</li>
    <li><b>INDISPONIBLE</b> : l’API ne répond pas ; le dernier cache valide est conservé.</li>
    <li>Les valeurs « — » signifient que TopScorers ne fournit pas ce détail à cet instant, pas que le joueur a forcément zéro.</li>
  </ul>
</div>

<div class="card p-3">
  <h3 class="h5">Bonnes pratiques pour gagner</h3>
  <ol class="mb-0">
    <li>Vérifie toujours <b>Compo</b> avant le premier match : chaque place vide coûte 50 points.</li>
    <li>Place l’<b>offre conseillée</b> assez tôt en cas d’égalité, car la première offre identique est prioritaire.</li>
    <li>Ne dépasse jamais le <b>plafond absolu</b> sous l’effet de la concurrence.</li>
    <li>Privilégie le <b>gain pts/match</b> pour renforcer Droken et le ROI pour une opération de revente.</li>
    <li>Garde une réserve de budget pour les opportunités suivantes et évite un solde négatif avant une journée.</li>
    <li>Une faible confiance signifie « données insuffisantes », pas forcément « mauvais joueur ».</li>
  </ol>
</div>
"""
    sections.append({"id":"tabHelp","title":"Aide","content": legend_html})

    html = build_html_page(sections, dyn_threshold)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Dashboard généré: {OUTPUT_HTML}")

# ----------------- TRADE PLAN (placeholder) -----------------
def build_trade_plan(*args, **kwargs):
    return pd.DataFrame(), 0, {}

if __name__ == "__main__":
    main()
