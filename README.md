# Scenario Fan — Rolling Horizon Hydro-Thermal Scheduling

Fansi/SOVN-style two-stage stochastic linear programming model with Benders decomposition. Hydro-dominated power system with wind integration, 9-reservoir cascade, 364-day rolling horizon.

## Project Structure

```
.
├── Rolling_scenario_fan.py     # Legacy entry point (thin wrapper)
├── index.html                  # Interactive config & results dashboard
├── CLAUDE.md                   # AI assistant domain context
├── README.md                   # This file
│
├── c/                          # Main package
│   ├── __init__.py             # Public API exports
│   ├── config.py               # ModelParams dataclass — all configurables
│   ├── model.py                # Pyomo model builders (first + second stage)
│   ├── solver.py               # Benders decomposition + scenario solver
│   ├── io.py                   # Data loading + results export (CSV/JSON/HTML)
│   └── run.py                  # Rolling-horizon orchestrator + CLI
│
├── b_read_dataset/             # Data I/O utilities
│   ├── __init__.py
│   ├── h5_topology_data_reading.py  # HDF5 topology parser
│   ├── read_inflow_daily.py         # Inflow CSV reader (Mm³ → m³/s)
│   ├── read_load_daily.py           # Load Excel reader with scaling
│   └── read_wind_scenarios_daily.py # Wind MinMax scaling reader
│
└── a_dataset/                  # Input data (not tracked)
    ├── regulated_inflow_newscen.csv
    ├── unregulated_inflow_newscen.csv
    ├── consumption-weekly-3years.xlsx
    ├── wind_production_inMWh.xlsx
    ├── topology.h5
    └── watervalues_mm3.csv
```

## Quick Start

```bash
# Run one scenario set (default: CSV output)
python -m c.run 0

# HTML report with embedded Chart.js
python -m c.run 0 --html

# All formats
python -m c.run 0 --all

# Custom parameters
python -m c.run 0 --load 400 --wind 50 --scenarios 20 --json
```

Legacy entry point:
```bash
python Rolling_scenario_fan.py 0
```

## Model Formulation

### Two-Stage Stochastic LP

**First Stage (Day-Ahead):** 1 time step, detailed hydro constraints.

min Σ_t (C_shed·r_t + C_byp·q_b_t + C_spl·q_s_t + C_wind·w_c_t) + α

where α = expected future cost, constrained by Benders cuts.

**Second Stage (Scenario Fan):** K inflow scenarios × W wind traces = K×W deterministic LPs, each 364 time steps.

Each scenario minimizes its probability-weighted cost. Duals of the k=1 reservoir balance give marginal water values λ = ∂Obj/∂V.

### Benders Cut (FIXED)

```
α ≥ Σ_k [ Obj^k_RT + Σ_m λ^k_m · (V_m,1 − V̄^k_m) ]
```

The cut approximates the future cost as a function of ending reservoir volume. λ is negative (more water → lower future cost). The cut correctly makes α decrease when reservoir increases.

### Reservoir Balance

```
V_{t+1} − V_t = 0.0864 × (I_reg + I_unreg − q_d − q_b − q_s + upstream_inflow)
```

Unit conversion: m³/s × 86400 s/day ÷ 10⁶ = 0.0864 Mm³/day.

## Bugs Found and Fixed

### Critical Bugs

| Bug | Location | Description | Fix |
|-----|----------|-------------|-----|
| Benders cut sign error | `solver.py:113` | Formula used `-λ·(V+V̄)` — made α **increase** with more water | Changed to `+λ·(V−V̄)` — correct Taylor expansion |
| Scenario probability ×3 | `config.py:57` | `Pr = 1/num_scenarios` ignored wind dimension, inflating Benders cut by factor `wind_scenarios=3` | `Pr = 1/(num_scenarios × wind_scenarios)` |
| `rolling_horizon` not imported | `Rolling_scenario_fan.py:14` | `NameError` when calling legacy `fansi_rolling()` | Added to import |
| `model_fs.InitRes` after loop | `run.py:65` | `InitRes` only exists when `batch=1`; after loop `batch=364`, access raises `AttributeError` | Capture day-1 initial reservoir before loop |

### Risk Fixes

| Issue | Location | Fix |
|-------|----------|-----|
| Convergence: `abs(sum(...))` allows cross-module cancellation | `solver.py:145` | Changed to `sum(abs(...))` |
| `rt_reservoir` dict overwrites on each `k` | `solver.py:127` | Use `k=1` explicitly instead of nested comprehension |
| `load_data_fs` loop overwrites key | `io.py:47` | Direct indexing `[0][0]` since `nb_day_steps_da=1` |
| `model.H.data()` non-portable Pyomo API | `io.py:113,122` | Changed to standard `for h in model.H` |

## Configuration

### Via HTML Portal

Open `index.html` in a browser. Two interactive portals:

1. **Data Import** — Set paths to all 6 dataset files + output directory
2. **Parameter Settings** — All 18 model parameters with defaults pre-filled

Settings persist to `localStorage`. Export as `fansi_config.json` for use with Python backend.

### Via Python

```python
from c.config import ModelParams
from c.run import rolling_horizon

params = ModelParams(
    num_scenarios=10,
    wind_scenarios=3,
    max_load_hydro=350,
    max_wind_cap=30,
    solver_name='cplex_direct',
)

results, reservoir_opt, elapsed = rolling_horizon(params)
```

### Default Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `nb_day_steps` | 364 | Rolling horizon length [days] |
| `num_scenarios` | 10 | Inflow scenario fan size |
| `wind_scenarios` | 3 | Wind traces per inflow scenario |
| `cost_shedding` | 5000 | Load shedding penalty [€/MWh] |
| `cost_spillage` | 100 | Water spillage cost [€/m³s] |
| `cost_bypass` | 80 | Bypass cost [€/m³s] |
| `max_load_hydro` | 350 | Peak load in hydro area [MW] |
| `max_wind_cap` | 30 | Installed wind capacity [MW] |
| `init_reservoir_frac` | 0.65 | Initial reservoir ÷ V_max |
| `lb_reservoir_frac` | 0.10 | Minimum reservoir ÷ V_max |
| `solver_name` | `cplex_direct` | Pyomo solver |
| `benders_tol` | 0.001 | Convergence tolerance |

## Output Formats

### CSV (default)
```
output_c/
├── hydro_production_0.csv     # Per-module hydro [MW]
├── reservoir_levels_0.csv     # Daily reservoir levels [Mm³]
├── wind_0.csv                 # Wind prod + curtailment [MW]
├── water_values_DA_0.csv      # Day-ahead water values [€/Mm³]
├── spillage_0.csv             # Per-module spillage [m³/s]
├── bypass_0.csv               # Per-module bypass [m³/s]
└── system_0.csv               # Load shedding + energy price
```

### JSON
Single structured file with all results + metadata + elapsed time.

### HTML
Self-contained report with Chart.js — no server needed. Includes:
- KPIs (max hydro, avg wind, total load shedding)
- Hydro production per module (9 traces)
- Reservoir trajectory (9 traces)
- Water value evolution
- Wind production & curtailment
- Spillage & bypass
- Energy price (system lambda)

## Dependencies

- Python ≥ 3.9
- Pyomo ≥ 6.0
- CPLEX or Gurobi solver (GLPK/CBC for small tests)
- pandas, numpy, h5py, scikit-learn, openpyxl


