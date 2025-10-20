import datetime as dt
import pandas as pd

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
    BOOTSTRAP_CSS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
    BOOTSTRAP_JS  = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"

    return f"""<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TopScorers — Dashboard</title>
<link href="{BOOTSTRAP_CSS}" rel="stylesheet">
<style>
  /* ====== CHARTE LHC ====== */
  :root {{
    --lhc-red:#C8102E;
    --lhc-green:#19C37D;
    --lhc-bg:#0E1116;
    --lhc-card:#171A22;
    --lhc-text:#FFFFFF;
    --lhc-black:#000000;
    --lhc-muted:#C7CED9;
    --row-border:#2B3140;

    /* Forcer Bootstrap */
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

  /* ✅ Forcer la couleur du texte dans les tableaux */
  .table td, .table th {{
    color: var(--lhc-text) !important;
  }}
  .table th {{
    font-weight: 600;
    color: var(--lhc-muted) !important;
  }}

  /* Liens des joueurs */
  table a.pm-open {{
    color: var(--lhc-text);
    text-decoration: none;
    font-weight: 500;
  }}
  table a.pm-open:hover {{
    color: var(--lhc-red);
    text-decoration: underline;
  }}

  .table .score-mustbuy td {{
  background-color: #baf7d6 !important;
  color: var(--lhc-black) !important;   /* 🔴 texte noir */
  font-weight: 600;
  text-shadow: none;
}}

.table .score-mustbuy a.pm-open {{
  color: var(--lhc-black) !important;
  text-decoration: underline;
}}

  input.form-control-sm, select.form-select-sm {{
    background:#10141C; color:var(--lhc-text); border:1px solid var(--row-border);
  }}
  input.form-control-sm:focus, select.form-select-sm:focus {{
    background:#0C1016; border-color:var(--lhc-red);
    box-shadow: 0 0 0 .15rem rgba(200,16,46,.15);
  }}

  /* Tri visuel */
  th.sort-asc::after  {{ content:" \\25B2"; font-size:.7em; color:var(--lhc-muted); }}
  th.sort-desc::after {{ content:" \\25BC"; font-size:.7em; color:var(--lhc-muted); }}
  th.sort-asc, th.sort-desc {{ color:#fff; }}

  /* Must-buy */
  .score-mustbuy td {{ background-color:#baf7d6 !important; text-shadow:0 1px 1px rgba(0,0,0,.15); }}

  /* Badges */
  .badge-chip {{ display:inline-block; padding:.15rem .45rem; border-radius:.5rem; font-size:.75rem; border:1px solid #d0d5dd; white-space:nowrap; }}
  .chip-owner   {{ background:#ffffff; color:#000; border-color:#d0d5dd; }}
  .chip-foreign {{ background:#ffe3e7; color:#000; border-color:#ff9aa9; }}

  /* Modal */
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

  // --- Filtre rapide ---
  document.querySelectorAll('[data-quickfilter-table]').forEach(function(input){{
    var tableId = input.getAttribute('data-quickfilter-table');
    var tbl = document.getElementById(tableId);
    if (!tbl || !tbl.tBodies || !tbl.tBodies[0]) return;
    input.addEventListener('input', function(){{
      var q = (this.value || '').toLowerCase();
      Array.prototype.slice.call(tbl.tBodies[0].rows).forEach(function(row){{
        var txt = row.innerText.toLowerCase();
        row.style.display = (q === '' || txt.indexOf(q) !== -1) ? '' : 'none';
      }});
      if (tbl._pager) tbl._pager.rebuild();
    }});
  }});

  // --- Tri colonnes ---
  function enableTableSort(table) {{
    if (!table || !table.tHead || !table.tBodies || !table.tBodies[0]) return;
    var ths = table.tHead.rows[0].cells;
    Array.prototype.forEach.call(ths, function(th, idx){{
      th.style.cursor = 'pointer';
      th.addEventListener('click', function(){{
        var tbody = table.tBodies[0];
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        var isAsc = !th.classList.contains('sort-asc');
        Array.prototype.forEach.call(ths, function(other) {{
          if (other !== th) other.classList.remove('sort-asc','sort-desc');
        }});
        th.classList.toggle('sort-asc', isAsc);
        th.classList.toggle('sort-desc', !isAsc);

        var collator = new Intl.Collator(undefined, {{ numeric: true, sensitivity: 'base' }});
        rows.sort(function(a,b){{
          var aText = (a.cells[idx] ? a.cells[idx].innerText : '').trim();
          var bText = (b.cells[idx] ? b.cells[idx].innerText : '').trim();
          return isAsc ? collator.compare(aText, bText) : collator.compare(bText, aText);
        }});
        rows.forEach(function(r){{ tbody.appendChild(r); }});
        if (table._pager) table._pager.rebuild();
      }});
    }});
  }}

  // --- Pagination légère ---
  function enablePager(table, pageSize) {{
    if (!table || !table.tBodies || !table.tBodies[0]) return;
    var tbody = table.tBodies[0];
    var pager = {{
      page: 1,
      size: pageSize || 25,
      rebuild: function(){{
        var all = Array.prototype.slice.call(tbody.rows);
        var visible = all.filter(function(r){{ return r.style.display !== 'none'; }});
        var total = visible.length;
        var pages = Math.max(1, Math.ceil(total / pager.size));
        pager.page = Math.min(pager.page, pages);
        var start = (pager.page - 1) * pager.size;
        var end   = start + pager.size;
        var i, r;
        for (i=0;i<visible.length;i++) {{
          r = visible[i];
          r.style.display = (i >= start && i < end) ? '' : 'none';
        }}
        if (!table._pagerEl) {{
          table._pagerEl = document.createElement('div');
          table._pagerEl.className = 'd-flex justify-content-between align-items-center mt-2';
          table.parentNode.appendChild(table._pagerEl);
        }}
        var info = 'Page ' + pager.page + ' / ' + pages + ' — ' + total + ' lignes';
        var btnPrev = '<button class="btn btn-sm btn-outline-light me-2" data-act="prev">&laquo;</button>';
        var btnNext = '<button class="btn btn-sm btn-outline-light ms-2" data-act="next">&raquo;</button>';
        table._pagerEl.innerHTML = '<div class="small text-secondary">'+info+'</div><div>'+btnPrev+btnNext+'</div>';
        table._pagerEl.querySelector('[data-act="prev"]').onclick = function(){{
          if (pager.page > 1) {{ pager.page--; pager.rebuild(); }}
        }};
        table._pagerEl.querySelector('[data-act="next"]').onclick = function(){{
          if (pager.page < pages) {{ pager.page++; pager.rebuild(); }}
        }};
      }}
    }};
    table._pager = pager;
    pager.rebuild();
  }}

  // --- Colonnes avancées (toggle) ---
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

  // --- Surlignage must-buy ---
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
      var j, hits, trials, r, txt, v;
      for (j=lastIdx; j>=0; j--) {{
        hits=0; trials=0;
        for (var k=0; k<Math.min(5, rows.length); k++) {{
          r = rows[k];
          txt = (r.cells[j] ? r.cells[j].innerText : '').trim().replace(',', '.');
          v = parseFloat(txt);
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

  // --- Helpers colonnes ---
  function colIndexByName(table, namePartLower) {{
    namePartLower = (namePartLower||'').toLowerCase();
    if (!table || !table.tHead) return -1;
    var ths = table.tHead.rows[0].cells;
    for (var i=0;i<ths.length;i++) {{
      var t = (ths[i].innerText||'').trim().toLowerCase();
      if (t.indexOf(namePartLower) >= 0) return i;
    }}
    return -1;
  }}

  // --- Pop-up joueur (jolie) ---
  var modalEl = document.getElementById('playerModal');
  var bsModal = modalEl ? new bootstrap.Modal(modalEl) : null;

  function initials(name) {{
    if (!name) return '⚑';
    var parts = name.trim().split(/\\s+/);
    if (!parts.length) return '⚑';
    var a = parts[0] ? parts[0].charAt(0) : '';
    var b = parts.length>1 ? parts[parts.length-1].charAt(0) : '';
    var up = (a+b).toUpperCase();
    return up || '⚑';
  }}

  function enhancePlayerCells(table) {{
    if (!table || !table.tBodies || !table.tBodies[0]) return;
    var idxJ = colIndexByName(table, 'joueur'); if (idxJ < 0) return;
    Array.prototype.slice.call(table.tBodies[0].rows).forEach(function(row){{
      var cell = row.cells[idxJ];
      if (!cell) return;
      if (cell.querySelector('a.pm-open')) return;
      var name = (cell.innerText||'').trim();
      if (!name) return;
      var link = document.createElement('a');
      link.href = '#';
      link.className = 'pm-open';
      link.textContent = name;
      link.addEventListener('click', function(ev){{
        ev.preventDefault();
        openPlayerModalFromRow(table, row);
      }});
      cell.textContent = '';
      cell.appendChild(link);
    }});
  }}

  function openPlayerModalFromRow(tbl, row) {{
    if (!bsModal) return;

    function getTxt(colName) {{
      var idx = colIndexByName(tbl, (colName||'').toLowerCase());
      if (idx < 0) return '';
      return (row.cells[idx] ? row.cells[idx].innerText : '').trim();
    }}
    function getHTML(colName) {{
      var idx = colIndexByName(tbl, (colName||'').toLowerCase());
      if (idx < 0) return '';
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

    // Header
    modalEl.querySelector('#pmAvatar').textContent = initials(name);
    modalEl.querySelector('#pmName').textContent   = name;
    modalEl.querySelector('#pmTeamBadge').textContent = team ? team : '—';
    modalEl.querySelector('#pmPosBadge').textContent  = pos;

    // Body values
    modalEl.querySelector('#pmPts').textContent   = pts;
    var valTxt = val;
    if (prix) valTxt = valTxt + ' / ' + prix;
    modalEl.querySelector('#pmVal').textContent   = valTxt;
    modalEl.querySelector('#pmAlpha').textContent = alpha;

    var sparkEl = modalEl.querySelector('#pmSpark');
    sparkEl.innerHTML = spark || '<span class="text-secondary">Aucune donnée</span>';

    // détails
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

  // --- Init: tri, pager, toggles, popups + must-buy ---
  document.querySelectorAll('table').forEach(function(tbl){{
    enableTableSort(tbl);
    enablePager(tbl, 25);
    enableColumnToggles(tbl);
    enhancePlayerCells(tbl);
  }});
  ['tblVentes','tblRecos','tblAllPlayers','tblOwners','tblTradePlan','tblByPos','tblUnder','tblOver'].forEach(colorizeMustBuy);

}});
</script>
</body></html>"""

def df_to_html_table(df: pd.DataFrame, table_id: str, quick_placeholder="Filtrer…") -> str:
    """Rend un tableau HTML + barre de recherche. Pas de JS inline ici (ajouté dans build_html_page)."""
    if df is None or df.empty:
        return "<div class='text-secondary'>Aucune donnée à afficher.</div>"
    df2 = df.copy().where(pd.notna(df), "")

    # Cacher colonnes techniques ID
    drop_cols = [c for c in df2.columns if c.strip().lower() in ("id","id joueur","player id","player_id")]
    if drop_cols:
        df2 = df2.drop(columns=drop_cols)

    cols = list(df2.columns)
    thead = "<thead><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead>"

    # Marquer explicitement la cellule spark (meilleure mise en page SVG)
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
