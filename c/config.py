"""Model parameters and configuration loading for the Fansi scheduler."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_path(relative_path: str) -> str:
    """Resolve a user path independently of the process working directory."""
    path = Path(relative_path).expanduser()
    return str(path if path.is_absolute() else PROJECT_ROOT / path)

# 9-reservoir cascade module IDs (from SINTEF topology)
MODULES: List[str] = ['49904', '49905', '49906', '49907', '49908', '49909', '49910', '49911', '49912']
MODULE_RANGE = range(49904, 49913)


@dataclass
class ModelParams:
    """All configurable parameters for a rolling-horizon simulation."""

    # --- Horizon ---
    nb_day_steps: int = 364          # total days in rolling window
    nb_day_steps_da: int = 1         # first-stage length (day-ahead, 1 day)

    # --- Scenarios ---
    num_scenarios: int = 10          # inflow scenarios (K in scenario fan)
    wind_scenarios: int = 3          # wind traces per inflow scenario
    scenarioset: int = 0             # starting year offset in dataset

    # --- Costs (€/MWh or €/m³s) ---
    cost_shedding: float = 5000.0    # load shedding penalty
    cost_spillage: float = 100.0     # water spillage cost
    cost_bypass: float = 80.0        # bypass cost
    cost_wind_curt: float = 0.0      # wind curtailment cost

    # --- Physical ---
    max_load_hydro: float = 350.0    # max load in hydro area [MW]
    max_wind_cap: float = 30.0       # installed wind capacity [MW]
    inflow_factor: float = 1.0       # inflow scaling factor
    init_reservoir_frac: float = 0.65  # initial reservoir as fraction of V_max
    lb_reservoir_frac: float = 0.10    # lower bound as fraction of V_max
    conversion: float = 0.0864       # m³/s → Mm³ per day (24*3600/1e6)

    # --- Solver ---
    solver_name: str = 'cplex_direct'
    benders_tol: float = 0.001       # convergence tolerance on reservoir change
    max_benders_iter: int = 20       # safety cap on iterations

    # --- File paths ---
    loc_regulated: str = field(default_factory=lambda: _project_path('a_dataset/regulated_inflow_newscen.csv'))
    loc_unregulated: str = field(default_factory=lambda: _project_path('a_dataset/unregulated_inflow_newscen.csv'))
    loc_load: str = field(default_factory=lambda: _project_path('a_dataset/consumption-weekly-3years.xlsx'))
    loc_wind: str = field(default_factory=lambda: _project_path('a_dataset/wind_production_inMWh.xlsx'))
    loc_topology: str = field(default_factory=lambda: _project_path('a_dataset/topology.h5'))
    loc_watervalues: str = field(default_factory=lambda: _project_path('a_dataset/watervalues_mm3.csv'))
    loc_output_dir: str = field(default_factory=lambda: _project_path('output_c'))

    # --- Areas ---
    areas: List[str] = field(default_factory=lambda: ['hydro'])
    load_area: str = 'NO1'

    # --- Derived ---
    @property
    def scenario_probability(self) -> Dict[int, float]:
        """Joint probability per (inflow, wind) scenario leaf.

        Each of the num_scenarios × wind_scenarios combinations is equally likely.
        """
        n = self.num_scenarios * self.wind_scenarios
        return {s + 1: 1.0 / n for s in range(self.num_scenarios)}

    @property
    def lb(self) -> float:
        return self.lb_reservoir_frac

    @property
    def fac_res(self) -> float:
        return self.init_reservoir_frac

    @classmethod
    def from_json(cls, config_path: str):
        """Load the JSON configuration exported by ``index.html``."""
        path = Path(config_path).expanduser().resolve()
        with path.open(encoding='utf-8') as config_file:
            config = json.load(config_file)

        data_paths = config.get('data_paths', {})
        parameters = config.get('parameters', {})
        if not isinstance(data_paths, dict) or not isinstance(parameters, dict):
            raise ValueError('Config fields "data_paths" and "parameters" must be objects')

        path_fields = {
            'regulated': 'loc_regulated',
            'unregulated': 'loc_unregulated',
            'load': 'loc_load',
            'wind': 'loc_wind',
            'topology': 'loc_topology',
            'watervalues': 'loc_watervalues',
            'output': 'loc_output_dir',
        }
        parameter_aliases = {
            'fac_res': 'init_reservoir_frac',
            'lb': 'lb_reservoir_frac',
            'solver': 'solver_name',
        }
        valid_parameters = set(cls.__dataclass_fields__) - set(path_fields.values())

        values = {}
        for key, value in data_paths.items():
            if key in path_fields:
                values[path_fields[key]] = _project_path(value)
        for key, value in parameters.items():
            field_name = parameter_aliases.get(key, key)
            if field_name in valid_parameters:
                values[field_name] = value

        return cls(**values)
