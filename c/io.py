"""Data loading and result saving helpers for the Fansi rolling-horizon model."""

import json
import os
from typing import Dict, List, Tuple

import pandas as pd
from pyomo.environ import value

from c.config import ModelParams, MODULES, MODULE_RANGE
from b_read_dataset import read_topology, read_and_adjust_load, read_wind_profile, read_inflow


# ═══════════════════════════════════════════════════════════════════════
#  Data Loading
# ═══════════════════════════════════════════════════════════════════════

def load_day_data(params: ModelParams, day: int):
    """Load all data needed for one day of the rolling horizon.

    Returns:
        wind_data_fs: {1: float} — first-stage wind capacity.
        wind_data_ss: {scen+1: {k+1: float}} — second-stage wind traces.
        load_data_fs: {('hydro', 1): float} — first-stage load.
        load_data_ss: {('hydro', k+1): float} — second-stage load.
        inflow_fs: {'regulated': {(mod, 1): float}, 'unregulated': {(mod, 1): float}}.
        inflow_ss: {'regulated': {scen+1: {(mod, k+1): float}}, ...}.
        inflow_initial: {'regulated': {mod: float}, 'unregulated': {mod: float}}.
    """
    # Wind
    wind_fs, wind_ss = read_wind_profile(
        loc=params.loc_wind, max_wind=params.max_wind_cap,
        T=day - 1, year=params.wind_scenarios, window_size=params.nb_day_steps,
    )
    wind_data_fs = {1: wind_fs}
    wind_data_ss = {
        s + 1: {k + 1: wind_ss[s][k] for k in range(params.nb_day_steps)}
        for s in range(params.wind_scenarios)
    }

    # Load
    load_fs_raw, load_ss_raw = read_and_adjust_load(
        loc=params.loc_load, area=params.load_area,
        max_load=params.max_load_hydro, T=day - 1, window_size=params.nb_day_steps,
    )
    # First stage: single time step (k=1), take first value
    load_data_fs = {('hydro', 1): load_fs_raw.values.tolist()[0][0]}
    load_data_ss = {
        ('hydro', k + 1): load_ss_raw.values.tolist()[k][0]
        for k in range(params.nb_day_steps)
    }

    # Inflow
    inflow_sce, inflow_initial = read_inflow(
        factor=params.inflow_factor,
        loc_re=params.loc_regulated, loc_un=params.loc_unregulated,
        tot_years=params.num_scenarios, window_size=params.nb_day_steps,
        T=day - 1, start_year=params.scenarioset,
    )

    inflow_fs = {
        'regulated': {(str(m), 1): inflow_initial['regulated'][str(m)] for m in MODULE_RANGE},
        'unregulated': {(str(m), 1): inflow_initial['unregulated'][str(m)] for m in MODULE_RANGE},
    }

    inflow_ss = {
        'regulated': {
            s + 1: {
                (str(m), k + 1): inflow_sce['regulated'][s + 1][str(m)][k]
                for m in MODULE_RANGE for k in range(params.nb_day_steps)
            }
            for s in range(params.num_scenarios)
        },
        'unregulated': {
            s + 1: {
                (str(m), k + 1): inflow_sce['unregulated'][s + 1][str(m)][k]
                for m in MODULE_RANGE for k in range(params.nb_day_steps)
            }
            for s in range(params.num_scenarios)
        },
    }

    return (wind_data_fs, wind_data_ss,
            load_data_fs, load_data_ss,
            inflow_fs, inflow_ss, inflow_initial)


# ═══════════════════════════════════════════════════════════════════════
#  Result Collection
# ═══════════════════════════════════════════════════════════════════════

def init_results_dict(params: ModelParams, topology: dict) -> dict:
    """Create the empty results accumulator."""
    hseg = topology['hydro']['nb_seg']
    return {
        'hydro_P': {h: [] for h in MODULES},
        'discharge': {(h, seg): [] for h in MODULES for seg in hseg[h]},
        'wind_P': [],
        'wind_C': [],
        'load_shedding': {a: [] for a in params.areas},
        'water_value_DA': {h: [] for h in MODULES},
        'water_value_RT': {h: [] for h in MODULES},
        'spillage': {h: [] for h in MODULES},
        'bypass': {h: [] for h in MODULES},
        'energy_B': {a: [] for a in params.areas},
    }


def collect_day_results(results: dict, model_fs, model_ss, params: ModelParams):
    """Extract and append results from solved models for one day."""
    k_da = params.nb_day_steps_da

    for h in model_fs.H:
        results['hydro_P'][h].append(value(model_fs.hydro_prod[h, k_da]))
        results['water_value_DA'][h].append(
            value(model_fs.dual[model_fs.ReservoirBalance[h, k_da]]))
        results['water_value_RT'][h].append(
            value(model_ss.dual[model_ss.ReservoirBalance[h, k_da]]))
        results['spillage'][h].append(value(model_fs.q_s[h, k_da]))
        results['bypass'][h].append(value(model_fs.q_b[h, k_da]))

    for hseg in model_fs.HSeg:
        results['discharge'][hseg].append(value(model_fs.q_d[hseg, k_da]))

    results['wind_P'].append(value(model_fs.wind_P[k_da]))
    results['wind_C'].append(value(model_fs.wind_C[k_da]))
    results['load_shedding']['hydro'].append(
        value(model_fs.load_shedding['hydro', k_da]))
    results['energy_B']['hydro'].append(
        value(model_fs.dual[model_fs.PowerBalance['hydro', k_da]]))


# ═══════════════════════════════════════════════════════════════════════
#  Saving
# ═══════════════════════════════════════════════════════════════════════

def _make_serializable(obj):
    """Convert numpy types to native Python for JSON serialization."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    return obj


def save_results_json(results: dict, reservoir_opt: dict, elapsed: float,
                      params: ModelParams, index: int):
    """Save all results as a structured JSON file."""
    os.makedirs(params.loc_output_dir, exist_ok=True)

    output = {
        'parameters': {
            'num_scenarios': params.num_scenarios,
            'wind_scenarios': params.wind_scenarios,
            'max_load': params.max_load_hydro,
            'max_wind': params.max_wind_cap,
            'inflow_factor': params.inflow_factor,
            'nb_day_steps': params.nb_day_steps,
        },
        'results': _make_serializable(results),
        'reservoir_level': _make_serializable(reservoir_opt),
        'elapsed_seconds': elapsed,
    }

    path = os.path.join(params.loc_output_dir, f'results_{index}.json')
    with open(path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f'Results saved to {path}')


def save_results_csv(results: dict, reservoir_opt: dict,
                     params: ModelParams, index: int):
    """Save key time series as CSV files."""
    os.makedirs(params.loc_output_dir, exist_ok=True)
    out = params.loc_output_dir

    def to_df(data_dict, col_prefix=''):
        """Convert {key: [values]} dict to DataFrame with days as index."""
        df = pd.DataFrame(data_dict)
        df.index = range(1, len(df) + 1)
        df.index.name = 'day'
        if col_prefix:
            df.columns = [f'{col_prefix}_{c}' for c in df.columns]
        return df

    # Hydro production per module
    to_df(results['hydro_P'], 'P_hydro').to_csv(
        os.path.join(out, f'hydro_production_{index}.csv'))

    # Reservoir levels
    reservoir_df = pd.DataFrame(reservoir_opt).T
    reservoir_df.index.name = 'day'
    reservoir_df.to_csv(os.path.join(out, f'reservoir_levels_{index}.csv'))

    # Wind
    wind_df = pd.DataFrame({
        'wind_production': results['wind_P'],
        'wind_curtailment': results['wind_C'],
    })
    wind_df.index = range(1, len(wind_df) + 1)
    wind_df.index.name = 'day'
    wind_df.to_csv(os.path.join(out, f'wind_{index}.csv'))

    # Water values (DA)
    to_df(results['water_value_DA'], 'WV_DA').to_csv(
        os.path.join(out, f'water_values_DA_{index}.csv'))

    # Spillage + Bypass
    spill_df = pd.DataFrame({
        f'spill_{h}': results['spillage'][h] for h in MODULES
    })
    spill_df.index = range(1, len(spill_df) + 1)
    spill_df.index.name = 'day'
    spill_df.to_csv(os.path.join(out, f'spillage_{index}.csv'))

    bypass_df = pd.DataFrame({
        f'byp_{h}': results['bypass'][h] for h in MODULES
    })
    bypass_df.index = range(1, len(bypass_df) + 1)
    bypass_df.index.name = 'day'
    bypass_df.to_csv(os.path.join(out, f'bypass_{index}.csv'))

    # Load shedding + energy balance dual
    misc_df = pd.DataFrame({
        'load_shedding': results['load_shedding']['hydro'],
        'energy_price': results['energy_B']['hydro'],
    })
    misc_df.index = range(1, len(misc_df) + 1)
    misc_df.index.name = 'day'
    misc_df.to_csv(os.path.join(out, f'system_{index}.csv'))

    print(f'CSV files saved to {out}/')


def save_results_html(results: dict, reservoir_opt: dict, elapsed: float,
                      params: ModelParams, index: int):
    """Generate a self-contained HTML report with embedded charts."""
    import json as _json

    os.makedirs(params.loc_output_dir, exist_ok=True)

    data_json = _json.dumps({
        'hydro_P': {str(k): v for k, v in results['hydro_P'].items()},
        'wind_P': results['wind_P'],
        'wind_C': results['wind_C'],
        'water_value_DA': {str(k): v for k, v in results['water_value_DA'].items()},
        'spillage': {str(k): v for k, v in results['spillage'].items()},
        'bypass': {str(k): v for k, v in results['bypass'].items()},
        'load_shedding': results['load_shedding']['hydro'],
        'energy_price': results['energy_B']['hydro'],
        'reservoir_level': {str(k): {str(k2): v2 for k2, v2 in v.items()}
                            for k, v in reservoir_opt.items()},
    })

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fansi Results — Scenario Set {index}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#0f172a;--panel:#1e293b;--border:#334155;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--green:#4ade80;--red:#f87171}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text)}}
header{{background:var(--panel);border-bottom:2px solid var(--accent);padding:1.25rem 2rem;text-align:center}}
header h1{{font-size:1.4rem;color:var(--accent)}}
.container{{max-width:1400px;margin:0 auto;padding:1.5rem}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem}}
.grid-3{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.25rem}}
.card{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:1rem}}
.card h3{{font-size:0.9rem;color:var(--accent);margin-bottom:0.75rem;text-transform:uppercase;letter-spacing:0.05em}}
canvas{{width:100%!important;max-height:320px}}
.kpi{{font-size:1.8rem;font-weight:700;color:var(--accent)}}
.kpi-label{{font-size:0.75rem;color:var(--muted)}}
footer{{text-align:center;padding:1.5rem;color:var(--muted);font-size:0.75rem}}
</style>
</head>
<body>
<header>
<h1>Scenario Fan — Rolling Horizon Results</h1>
<p>Scenario set {index} &middot; {params.num_scenarios} inflow × {params.wind_scenarios} wind &middot; {params.nb_day_steps} days &middot; {elapsed:.0f}s runtime</p>
</header>
<div class="container">
<div class="grid-3" style="margin-bottom:1.25rem">
<div class="card"><div class="kpi-label">Max Hydro</div><div class="kpi" id="kpi-hydro">-</div><div class="kpi-label">MW</div></div>
<div class="card"><div class="kpi-label">Avg Wind</div><div class="kpi" id="kpi-wind">-</div><div class="kpi-label">MW</div></div>
<div class="card"><div class="kpi-label">Load Shedding</div><div class="kpi" id="kpi-shed">-</div><div class="kpi-label">MWh total</div></div>
</div>
<div class="grid-2" style="margin-bottom:1.25rem">
<div class="card"><h3>Hydro Production</h3><canvas id="chart-hydro"></canvas></div>
<div class="card"><h3>Reservoir Levels</h3><canvas id="chart-reservoir"></canvas></div>
</div>
<div class="grid-2" style="margin-bottom:1.25rem">
<div class="card"><h3>Water Values (Day-Ahead)</h3><canvas id="chart-wv"></canvas></div>
<div class="card"><h3>Wind Production & Curtailment</h3><canvas id="chart-wind"></canvas></div>
</div>
<div class="grid-2" style="margin-bottom:1.25rem">
<div class="card"><h3>Spillage & Bypass</h3><canvas id="chart-spill"></canvas></div>
<div class="card"><h3>Energy Price (System Lambda)</h3><canvas id="chart-price"></canvas></div>
</div>
</div>
<footer>Fansi SOVN Model &middot; Benders Decomposition &middot; Pyomo + CPLEX</footer>
<script>
const DATA = {data_json};
const MODULES = {json.dumps(MODULES)};
const days = Array.from({{length: DATA.wind_P.length}}, (_, i) => i + 1);

function chart(id, labels, datasets) {{
  new Chart(document.getElementById(id), {{
    type: 'line', data: {{labels, datasets}},
    options: {{
      responsive: true,
      plugins: {{legend: {{labels: {{color: '#94a3b8', boxWidth: 12}}}}}},
      scales: {{
        x: {{ticks: {{color: '#64748b', maxTicksLimit: 12}}, grid: {{color: '#1e293b'}}}},
        y: {{ticks: {{color: '#64748b'}}, grid: {{color: '#1e293b'}}}}
      }}
    }}
  }});
}}

const colors = ['#38bdf8','#4ade80','#fbbf24','#f87171','#a78bfa','#fb923c','#2dd4bf','#e879f9','#60a5fa'];

chart('chart-hydro', days, MODULES.map((m, i) => ({{
  label: m, data: DATA.hydro_P[m] || [], borderColor: colors[i], tension: 0.1, pointRadius: 0
}})));

chart('chart-wind', days, [
  {{label: 'Wind Production', data: DATA.wind_P, borderColor: '#4ade80', tension: 0.1, pointRadius: 0}},
  {{label: 'Wind Curtailment', data: DATA.wind_C, borderColor: '#f87171', tension: 0.1, pointRadius: 0}}
]);

chart('chart-wv', days, MODULES.map((m, i) => ({{
  label: m, data: DATA.water_value_DA[m] || [], borderColor: colors[i], tension: 0.1, pointRadius: 0
}})));

chart('chart-spill', days, [
  ...MODULES.map((m, i) => ({{label: 'Spill ' + m, data: DATA.spillage[m] || [], borderColor: colors[i], borderDash: [4,2], tension: 0.1, pointRadius: 0}})),
  ...MODULES.map((m, i) => ({{label: 'Byp ' + m, data: DATA.bypass[m] || [], borderColor: colors[i], tension: 0.1, pointRadius: 0}}))
]);

chart('chart-price', days, [
  {{label: 'Energy Price [€/MWh]', data: DATA.energy_price, borderColor: '#fbbf24', tension: 0.1, pointRadius: 0}}
]);

// Reservoir chart
const resLabels = Object.keys(DATA.reservoir_level).sort((a,b) => Number(a)-Number(b));
new Chart(document.getElementById('chart-reservoir'), {{
  type: 'line',
  data: {{
    labels: resLabels,
    datasets: MODULES.map((m, i) => ({{
      label: m,
      data: resLabels.map(d => DATA.reservoir_level[d] ? DATA.reservoir_level[d][m] : null),
      borderColor: colors[i], tension: 0.1, pointRadius: 0
    }}))
  }},
  options: {{
    responsive: true,
    plugins: {{legend: {{labels: {{color: '#94a3b8', boxWidth: 12}}}}}},
    scales: {{
      x: {{ticks: {{color: '#64748b', maxTicksLimit: 12}}, grid: {{color: '#1e293b'}}}},
      y: {{ticks: {{color: '#64748b'}}, grid: {{color: '#1e293b'}}}}
    }}
  }}
}});

// KPIs
const hp = Object.values(DATA.hydro_P).flat().filter(v => v != null);
document.getElementById('kpi-hydro').textContent = hp.length ? Math.max(...hp).toFixed(0) : '-';
document.getElementById('kpi-wind').textContent = DATA.wind_P.length ? (DATA.wind_P.reduce((a,b)=>a+b,0)/DATA.wind_P.length).toFixed(1) : '-';
document.getElementById('kpi-shed').textContent = DATA.load_shedding.length ? DATA.load_shedding.reduce((a,b)=>a+b,0).toFixed(0) : '-';
</script>
</body>
</html>'''

    path = os.path.join(params.loc_output_dir, f'report_{index}.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'HTML report saved to {path}')
