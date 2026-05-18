"""
Rolling-horizon hydro-thermal scheduling with scenario fan and Benders decomposition.

This is a thin wrapper around the `c` package. For new code, use:
    from c.run import rolling_horizon, run_fansi

Legacy API preserved via `fansi_rolling()` and `run_fansi_saveindata()`.
"""

import sys

from c.config import ModelParams
# c.run imports Pyomo — only import when actually running
from c.run import rolling_horizon, run_fansi


def fansi_rolling(loc_re, loc_un, loc_load, num_scen=1, scenarioset=0,
                  wind_sec=3, wind_max=50, inflow_factor=1, load=350):
    """Legacy wrapper returning (results, elapsed_seconds, benders_data).

    See c.run.rolling_horizon for the refactored version.
    """
    params = ModelParams(
        loc_regulated=loc_re,
        loc_unregulated=loc_un,
        loc_load=loc_load,
        num_scenarios=num_scen,
        scenarioset=scenarioset,
        wind_scenarios=wind_sec,
        max_wind_cap=wind_max,
        inflow_factor=inflow_factor,
        max_load_hydro=load,
    )
    results, reservoir_opt, elapsed = rolling_horizon(params)
    return results, elapsed, {}


def run_fansi_saveindata(index):
    """Legacy wrapper. See c.run.run_fansi for the refactored version."""
    params = ModelParams(
        scenarioset=index,
        num_scenarios=10,
        wind_scenarios=3,
        max_wind_cap=30,
        inflow_factor=1,
        max_load_hydro=350,
    )
    return run_fansi(index, params)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python Rolling_scenario_fan.py <index> [--json] [--html] [--all]")
        sys.exit(1)

    index = int(sys.argv[1])
    if '--all' in sys.argv:
        fmt = 'all'
    elif '--html' in sys.argv:
        fmt = 'html'
    elif '--json' in sys.argv:
        fmt = 'json'
    else:
        fmt = 'csv'

    params = ModelParams(
        scenarioset=index,
        num_scenarios=10,
        wind_scenarios=3,
        max_wind_cap=30,
        inflow_factor=1,
        max_load_hydro=350,
    )
    run_fansi(index, params, fmt=fmt)
