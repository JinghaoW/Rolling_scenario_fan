# Scenario Fan — Rolling Horizon Hydro-Thermal Scheduling

Fansi/SOVN-style two-stage stochastic linear programming model with Benders decomposition. Hydro-dominated power system with wind integration, 9-reservoir cascade, 364-day rolling horizon.

## Project Structure

```
.
├── Rolling_scenario_fan.py     # Legacy entry point (thin wrapper)
├── index.html                  # Interactive config & results dashboard
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
├── b_read_dataset/             # Data I/O utilities. This is your dataset. The orginal dataset has been removed
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
# Install the project and its dependencies once
pip install -e .

# The installed command works from any directory
fansi 0

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

## Docker

The image uses Python 3.11 and includes the open-source GLPK solver. Python
dependencies are installed from `requirements.txt`, and the application runs as
the non-root `appuser` account.

Input files are not copied into the image. Compose mounts `a_dataset` read-only at
`/app/a_dataset` and writes generated reports to the host `output_c` directory.

### Build and run with Compose

```bash
# Build the image
docker compose build

# Run scenario set 0 with GLPK and the default parameters
docker compose up

# Run with custom CLI arguments
docker compose run --rm fansi 0 --solver glpk --scenarios 5 --json

# Display all supported command-line options
docker compose run --rm fansi --help
```

### Pull the image from GitHub

Every push to `master` publishes a prebuilt image to GitHub Container Registry:

```bash
docker pull ghcr.io/jinghaow/rolling_scenario_fan:latest
docker run --rm \
  -v "$(pwd)/a_dataset:/app/a_dataset:ro" \
  -v "$(pwd)/output_c:/app/output_c" \
  ghcr.io/jinghaow/rolling_scenario_fan:latest 0 --solver glpk --json
```

Tags beginning with `v` (for example, `v1.0.0`) also publish a matching image
tag. The image contains the application and GLPK, but datasets remain external.

The default command is equivalent to:

```bash
python -m c.run 0 --solver glpk
```

The complete rolling horizon covers 364 days and may take considerable time. Stop
an attached Compose run with `Ctrl+C`.

### Run with Docker directly

```bash
docker build -t scenario-fan .
docker run --rm \
  -v "$(pwd)/a_dataset:/app/a_dataset:ro" \
  -v "$(pwd)/output_c:/app/output_c" \
  scenario-fan 0 --solver glpk --html
```

On PowerShell, use `${PWD}` instead of `$(pwd)`:

```powershell
docker run --rm `
  -v "${PWD}/a_dataset:/app/a_dataset:ro" `
  -v "${PWD}/output_c:/app/output_c" `
  scenario-fan 0 --solver glpk --html
```

If a newly installed Docker command is not recognized, reopen the terminal so the
updated `PATH` is loaded. To use a licensed commercial solver, install its runtime
and license in a derived image and pass the corresponding `--solver` value.

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


## Configuration

### Via HTML Portal

Open `index.html` in a browser. Two interactive portals:

1. **Data Import** — Set paths to all 6 dataset files + output directory
2. **Parameter Settings** — All 18 model parameters with defaults pre-filled

Settings persist to `localStorage`. Export as `fansi_config.json` for use with Python backend.

Relative paths in the exported file are resolved from the project root, independent
of the current terminal directory. Absolute Windows and Linux paths are also
supported. Run an exported configuration with:

```bash
fansi --config /path/to/fansi_config.json
```

The scenario index and selected CLI options can override exported values:

```bash
fansi 2 --config /path/to/fansi_config.json --solver glpk
```

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
- The necessary packages are installed with `pip install -r requirements.txt`, including:
- Python 3.9 or later
- Pyomo ≥ 6.0
- CPLEX or Gurobi solver (GLPK/CBC for small tests)
- pandas, numpy, h5py, scikit-learn, openpyxl
