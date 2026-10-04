"""Behavioral tests for the benchmark results dashboard (issue #744).

assets/benchmark-dashboard.js is DOM-coupled (no jsdom in this repo, matching
the rest of the web profiler's test story - see test_js_parity.py's #740
tests), so this drives the REAL file with a minimal hand-built DOM stub
rather than re-implementing its logic in the test. Every expected number is
computed from the real results/*.csv files via pandas rather than hardcoded,
so this stays correct as the benchmark harness's results/ evolves (no paper
freeze is in effect - see CLAUDE.md).
"""

import json
import subprocess
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# A minimal DOM stub: enough getElementById/createElement/appendChild/
# addEventListener plumbing to actually execute assets/benchmark-dashboard.js
# end to end (fetch mocked to serve the real results/ CSVs), then drive a
# filter-select change, a "significant only" checkbox toggle, a sort-header
# click, a filter reset, and a tab switch - the same interactions a person
# would perform in a browser - and read back what actually got rendered.
_DOM_STUB = r"""
'use strict';
var fs = require('fs');
var path = require('path');
var REPO = process.argv[1];

function makeEl(id) {
  var el = {
    id: id,
    _listeners: {},
    dataset: {},
    style: { setProperty: function () {} },
    classList: { add: function () {}, remove: function () {}, contains: function () { return false; } },
    hidden: false,
    textContent: '',
    _innerHTML: '',
    parentElement: { hidden: false },
    addEventListener: function (type, fn) {
      (el._listeners[type] = el._listeners[type] || []).push(fn);
    },
    setAttribute: function (k, v) { el['attr_' + k] = v; },
    getAttribute: function (k) { return el['attr_' + k]; },
    appendChild: function (child) { (el._children = el._children || []).push(child); return child; },
    querySelectorAll: function (sel) {
      if (sel === '.bench-sort-btn') return el._sortButtons || [];
      return [];
    },
    click: function () { (el._listeners.click || []).forEach(function (f) { f(); }); },
  };
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return el._innerHTML; },
    set: function (html) {
      el._innerHTML = html;
      el._sortButtons = [];
      var re = /class="bench-sort-btn" data-field="([^"]+)"/g, m;
      while ((m = re.exec(html))) {
        (function (field) {
          var btn = { dataset: { field: field }, _listeners: {},
            addEventListener: function (t, f) { (btn._listeners[t] = btn._listeners[t] || []).push(f); },
            click: function () { (btn._listeners.click || []).forEach(function (f) { f(); }); } };
          el._sortButtons.push(btn);
        })(m[1]);
      }
    },
  });
  return el;
}

var ids = ['loadBundledBtn', 'benchDropzone', 'benchFileInput', 'benchError', 'benchStatus',
  'benchResults', 'benchFilters', 'significantOnlyInput', 'benchSummary', 'benchTable',
  'benchChart', 'benchChartNote', 'benchChartBlock', 'benchExportBtn', 'benchResetBtn',
  'benchClearBtn', 'benchLegend'];
var elements = {};
ids.forEach(function (id) { elements[id] = makeEl(id); });

var createdSelects = {};
global.document = {
  getElementById: function (id) {
    if (!elements[id]) elements[id] = makeEl(id);
    return elements[id];
  },
  querySelectorAll: function (sel) {
    if (sel === '.bench-tab') return global.__tabButtons;
    return [];
  },
  createElement: function (tag) {
    var node = makeEl('(created:' + tag + ')');
    node.tagName = tag;
    node.appendChild = function (child) {
      (node._children = node._children || []).push(child);
      if (tag === 'label' && child.tagName === 'select' && child.dataset.field) {
        createdSelects[child.dataset.field] = child;
      }
      return child;
    };
    if (tag === 'select') {
      node._options = [];
      node.appendChild = function (opt) { node._options.push(opt); return opt; };
      Object.defineProperty(node, 'value', {
        get: function () { return node._value || ''; },
        set: function (v) { node._value = v; },
      });
    }
    return node;
  },
};

function makeTabButton(tab, selected) {
  var b = makeEl('tab-' + tab);
  b.dataset.tab = tab;
  b.setAttribute('aria-selected', String(selected));
  return b;
}
global.__tabButtons = [makeTabButton('fairness', true), makeTabButton('performance', false)];

var fetchMap = {
  'results/results_fairness.csv': fs.readFileSync(path.join(REPO, 'results', 'results_fairness.csv'), 'utf-8'),
  'results/results_performance.csv': fs.readFileSync(path.join(REPO, 'results', 'results_performance.csv'), 'utf-8'),
};
global.fetch = function (url) {
  return Promise.resolve({ ok: true, text: function () { return Promise.resolve(fetchMap[url]); } });
};
var lastBlob = null;
global.Blob = function (parts) { lastBlob = parts.join(''); };
global.URL = { createObjectURL: function () { return 'blob:x'; }, revokeObjectURL: function () {} };
global.document.body = { appendChild: function () {}, removeChild: function () {} };
global.window = global;
global.window.location = { search: process.argv[2] || '' };
global.history = { replaceState: function (a, b, u) { global.__lastUrl = u; } };

require(path.join(REPO, 'assets', 'profiler-engine.js'));

var results = {};

(async function () {
  require(path.join(REPO, 'assets', 'benchmark-dashboard.js'));

  if (!process.argv[2]) elements.loadBundledBtn.click(); // a shared link must load by itself
  await new Promise(function (r) { setTimeout(r, 20); });

  results.last_url_after_first_render = global.__lastUrl;
  results.results_hidden_after_load = elements.benchResults.hidden;
  results.summary_unfiltered = elements.benchSummary.textContent;

  var auditSelect = createdSelects['audit'];
  results.audit_select_found = !!auditSelect;
  if (auditSelect) {
    auditSelect.value = 'compas';
    (auditSelect._listeners.change || []).forEach(function (f) { f(); });
  }
  results.summary_after_audit_filter = elements.benchSummary.textContent;
  var otherAudits = ['ai_fair_recruitment', 'benefits_denial', 'german_credit_lending',
    'healthcare_readmission', 'insurance_denial', 'tenant_screening'];
  results.table_has_only_compas = otherAudits.every(function (a) {
    return elements.benchTable.innerHTML.indexOf(a) === -1;
  });

  elements.significantOnlyInput.checked = true;
  (elements.significantOnlyInput._listeners.change || []).forEach(function (f) { f(); });
  results.summary_after_significant_only = elements.benchSummary.textContent;

  function firstRowValue() {
    var body = (elements.benchTable.innerHTML.match(/<tbody>([\s\S]*?)<\/tbody>/) || [])[1] || '';
    var firstTr = (body.match(/<tr[^>]*>([\s\S]*?)<\/tr>/) || [])[1] || '';
    var tds = [];
    var re = /<td[^>]*>([^<]*)<\/td>/g, m;
    while ((m = re.exec(firstTr))) tds.push(m[1]);
    return tds[5] === undefined || tds[5] === '' ? null : parseFloat(tds[5]);
  }
  var valueBtn = elements.benchTable._sortButtons.filter(function (b) { return b.dataset.field === 'value'; })[0];
  results.value_sort_btn_found = !!valueBtn;
  if (valueBtn) valueBtn.click(); // ascending
  results.first_row_value_asc = firstRowValue();
  var valueBtn2 = elements.benchTable._sortButtons.filter(function (b) { return b.dataset.field === 'value'; })[0];
  if (valueBtn2) valueBtn2.click(); // descending
  results.first_row_value_desc = firstRowValue();
  results.aria_sort_value = /<th aria-sort="descending"><button[^>]*data-field="value"/.test(elements.benchTable.innerHTML);
  results.has_note_column = elements.benchTable.innerHTML.indexOf('<th>Note</th>') !== -1;
  results.small_badges = (elements.benchTable.innerHTML.match(/bench-small-badge/g) || []).length;
  results.legend_hidden = elements.benchLegend.hidden;

  results.export_btn_hidden = elements.benchExportBtn.hidden;
  elements.benchExportBtn.click();
  results.export_csv = lastBlob;

  // Signed-metric chart (#776): all-compas dpd/race has negative values.
  elements.benchResetBtn.click();
  [['metric', 'demographic_parity_diff'], ['protected_attribute', 'race']].forEach(function (kv) {
    var sel = createdSelects[kv[0]];
    sel.value = kv[1];
    (sel._listeners.change || []).forEach(function (f) { f(); });
  });
  results.signed_chart = elements.benchChart.innerHTML.indexOf('bar-track signed') !== -1;
  results.neg_bars = (elements.benchChart.innerHTML.match(/bar-fill [a-z]+ neg/g) || []).length;

  results.reset_disabled_before_reset = elements.benchResetBtn.disabled;
  elements.benchResetBtn.click();
  results.summary_after_reset = elements.benchSummary.textContent;
  results.significant_only_after_reset = elements.significantOnlyInput.checked;
  results.sort_cleared_after_reset = elements.benchTable.innerHTML.indexOf('Value ▼') === -1;
  results.url_after_reset = global.__lastUrl;
  results.reset_disabled_after_reset = elements.benchResetBtn.disabled;

  var perfTab = global.__tabButtons[1];
  perfTab.click();
  results.performance_tab_summary = elements.benchSummary.textContent;
  results.perf_chart_note_before = elements.benchChartNote.textContent;
  var metricSelect = createdSelects['metric'];
  metricSelect.value = 'accuracy';
  (metricSelect._listeners.change || []).forEach(function (f) { f(); });
  results.perf_chart_bars = (elements.benchChart.innerHTML.match(/class="bar-row"/g) || []).length;
  results.perf_chart_hidden = elements.benchChart.hidden;
  results.perf_chart_unsigned = elements.benchChart.innerHTML.indexOf('bar-track signed') === -1;

  elements.benchClearBtn.click();
  results.after_clear_summary = elements.benchSummary.textContent;
  results.after_clear_status = elements.benchStatus.textContent;

  results.last_url = global.__lastUrl;
  process.stdout.write(JSON.stringify(results));
})();
"""


def _run_dom_stub(search=""):
    completed = subprocess.run(
        ["node", "-e", _DOM_STUB, str(REPO_ROOT), search],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


def test_benchmark_dashboard_loads_filters_sorts_and_switches_tabs():
    """Drives the real assets/benchmark-dashboard.js through the interactions
    a person would perform in a browser, against the real results/*.csv, and
    checks every number against pandas ground truth rather than a hardcoded
    snapshot (results/ has no paper freeze and is expected to keep moving)."""
    fairness = pd.read_csv(REPO_ROOT / "results" / "results_fairness.csv")
    performance = pd.read_csv(REPO_ROOT / "results" / "results_performance.csv")

    total = len(fairness)
    total_significant = int(fairness["significant"].sum())
    compas = fairness[fairness["audit"] == "compas"]
    compas_significant = compas[compas["significant"]]

    r = _run_dom_stub()

    assert r["results_hidden_after_load"] is False
    assert r["summary_unfiltered"] == f"{total:,} of {total:,} rows shown · {total_significant:,} significant"

    assert r["audit_select_found"] is True
    assert r["table_has_only_compas"] is True
    assert r["summary_after_audit_filter"] == (
        f"{len(compas):,} of {total:,} rows shown · {int(compas['significant'].sum()):,} significant"
    )

    assert r["summary_after_significant_only"] == (
        f"{len(compas_significant):,} of {total:,} rows shown · {len(compas_significant):,} significant"
    )

    assert r["value_sort_btn_found"] is True
    assert r["first_row_value_asc"] == _rounded(compas_significant["value"].min())
    assert r["first_row_value_desc"] == _rounded(compas_significant["value"].max())

    assert r["performance_tab_summary"] == f"{len(performance):,} of {len(performance):,} rows shown"

    # #762: the performance tab charts too, once a metric is chosen.
    perf_accuracy = performance[performance["metric"] == "accuracy"]
    assert "Pick a metric" in r["perf_chart_note_before"]
    assert r["perf_chart_hidden"] is False
    assert r["perf_chart_bars"] == len(perf_accuracy)

    # #777 / #788 / #787: sort state is exposed, notes and small-sample rows are visible.
    assert r["aria_sort_value"] is True
    assert r["has_note_column"] is True
    assert (r["small_badges"] > 0) == bool(compas_significant["small_sample_warning"].any())

    # #776: a signed metric draws from a centre line, with negative bars marked.
    sel = fairness[(fairness["metric"] == "demographic_parity_diff") & (fairness["protected_attribute"] == "race")]
    assert r["signed_chart"] is bool((sel["value"] < 0).any())
    assert r["neg_bars"] == int((sel["value"] < 0).sum())
    assert r["perf_chart_unsigned"] is True

    # #784: clearing unloads the active tab's data.
    assert r["after_clear_summary"] == ""
    assert "Cleared performance" in r["after_clear_status"]

    # #761: the export is the filtered + sorted view, header included.
    assert r["export_btn_hidden"] is False
    lines = r["export_csv"].strip().split("\r\n")
    assert lines[0].startswith("audit,strategy,model,protected_attribute,metric,value")
    assert len(lines) == len(compas_significant) + 1
    assert round(float(lines[1].split(",")[5]), 4) == _rounded(compas_significant["value"].max())

    # Reset clears the active tab's dropdown filters and sort, as well as the
    # cross-view significance toggle, then rewrites the deep link to defaults.
    assert r["summary_after_reset"] == (
        f"{total:,} of {total:,} rows shown · {total_significant:,} significant"
    )
    assert r["reset_disabled_before_reset"] is False
    assert r["significant_only_after_reset"] is False
    assert r["sort_cleared_after_reset"] is True
    assert r["url_after_reset"] == "?tab=fairness"
    assert r["reset_disabled_after_reset"] is True


def _rounded(x):
    # Table cells are rendered with .toFixed(4); round the pandas ground
    # truth the same way for an exact equality check.
    return round(float(x), 4)


def test_benchmark_dashboard_ui_wiring_present_in_html_and_css():
    """Source-level check (matches the #740 precedent for DOM-coupled code):
    the dashboard page must expose the ids benchmark-dashboard.js binds to,
    and ROADMAP.md's Phase 5 checklist item should be checked off now that
    this exists."""
    html = (REPO_ROOT / "benchmark.html").read_text(encoding="utf-8")
    for expected_id in ["loadBundledBtn", "benchDropzone", "benchFileInput", "benchError",
                         "benchStatus", "benchResults", "benchFilters", "significantOnlyInput",
                         "benchSummary", "benchTable", "benchChart", "benchChartNote", "benchChartBlock",
                         "benchResetBtn"]:
        assert f'id="{expected_id}"' in html, expected_id

    css = (REPO_ROOT / "assets" / "benchmark.css").read_text(encoding="utf-8")
    assert ".bench-table" in css

    assert html.count('aria-live="polite"') >= 2  # #763
    assert 'id="benchExportBtn"' in html

    roadmap = (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert "- [x] Fairness dashboard for the benchmark harness results" in roadmap


def test_benchmark_dashboard_url_state_round_trips():
    """#764: a shared link restores tab/filter/significant-only/sort and
    auto-loads the bundled results; later renders keep the URL in sync."""
    fairness = pd.read_csv(REPO_ROOT / "results" / "results_fairness.csv")
    expected = fairness[(fairness["audit"] == "compas") & fairness["significant"]]

    r = _run_dom_stub("?tab=fairness&audit=compas&sig=1&sort=value:desc")
    # significant-only was restored from ?sig=1, so even before the stub toggles it
    # the audit-filtered count is already the significant subset.
    assert r["summary_after_audit_filter"].startswith(f"{len(expected):,} of")
    url = r["last_url_after_first_render"]
    for part in ("tab=fairness", "audit=compas", "sig=1", "sort=value%3Adesc"):
        assert part in url
    # ...and the stub's later switch to the performance tab rewrites it.
    assert "tab=performance" in r["last_url"]


def test_benchmark_dashboard_detect_kind_rejects_summary_csv():
    """#775: results/summary.csv (protected_attribute + mean_value, no value
    column) must not be mis-detected as a fairness file."""
    src = (REPO_ROOT / "assets" / "benchmark-dashboard.js").read_text(encoding="utf-8")
    start = src.index("function detectKind")
    fn = src[start:src.index("function ingest")]
    script = fn + "process.stdout.write(JSON.stringify([" + ",".join(
        f"detectKind({json.dumps(cols)})" for cols in (
            list(pd.read_csv(REPO_ROOT / "results" / "results_fairness.csv", nrows=0).columns),
            list(pd.read_csv(REPO_ROOT / "results" / "results_performance.csv", nrows=0).columns),
            list(pd.read_csv(REPO_ROOT / "results" / "summary.csv", nrows=0).columns),
        )) + "]));"
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    encoding="utf-8", check=True).stdout)
    assert out == ["fairness", "performance", None]
