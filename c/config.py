"""Model parameters and constants for the Fansi rolling-horizon hydro-thermal scheduler."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

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
    loc_regulated: str = 'a_dataset/regulated_inflow_newscen.csv'
    loc_unregulated: str = 'a_dataset/unregulated_inflow_newscen.csv'
    loc_load: str = 'a_dataset/consumption-weekly-3years.xlsx'
    loc_wind: str = 'a_dataset/wind_production_inMWh.xlsx'
    loc_topology: str = 'a_dataset/topology.h5'
    loc_output_dir: str = 'output_c'

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
