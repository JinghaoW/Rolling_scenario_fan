"""Rolling-horizon hydro-thermal scheduling with scenario fan and Benders decomposition.

Usage:
    python -m c.run <index>         # Run one scenario set
    python -m c.run <index> --json  # Save as JSON instead of CSV
"""

import sys
import time
import argparse

from pyomo.environ import value

from c.config import ModelParams, MODULES, MODULE_RANGE
from c.io import (
    load_day_data, init_results_dict, collect_day_results,
    save_results_json, save_results_csv, save_results_html,
)
from c.solver import benders_iteration
from b_read_dataset import read_topology


def rolling_horizon(params: ModelParams):
    """Run the full 364-day rolling-horizon simulation.

    Returns:
        results: Dict of all daily time series.
        reservoir_opt: Dict {day: {(mod): reservoir_level}}.
        elapsed: Wall-clock time in seconds.
    """
    topology = read_topology(loc=params.loc_topology)
    start = time.time()

    reservoir_opt = {}
    results = init_results_dict(params, topology)

    # Capture initial reservoir from day 1 (before it gets overwritten in loop)
    day1_initial = {
        str(m): topology['hydro']['V_max'][str(m)] * params.fac_res
        for m in MODULE_RANGE
    }
    model_fs_first = None

    for day in range(1, params.nb_day_steps + 1):
        print(f"{'='*10} day {day} {'='*10}")

        initial_reservoir = {
            str(m): topology['hydro']['V_max'][str(m)] * params.fac_res
            for m in MODULE_RANGE
        }

        # Load data for this day
        (wind_data_fs, wind_data_ss,
         load_data_fs, load_data_ss,
         inflow_fs, inflow_ss, _) = load_day_data(params, day)

        # Benders iteration
        system_log, it, model_fs, model_ss = benders_iteration(
            params, topology, day,
            load_data_fs=load_data_fs, load_data_ss=load_data_ss,
            inflow_fs=inflow_fs, wind_data_fs=wind_data_fs,
            wind_data_ss=wind_data_ss, inflow_ss=inflow_ss,
            initial_reservoir=initial_reservoir, reservoir_opt=reservoir_opt,
        )

        reservoir_opt[day] = system_log['Reservoir_ss'][it - 1]

        # Save first day's model to extract InitRes later
        if day == 1:
            model_fs_first = model_fs

        # Collect daily results
        collect_day_results(results, model_fs, model_ss, params)

    # Final reservoir state
    reservoir_opt[0] = day1_initial
    reservoir_opt[params.nb_day_steps] = {
        str(h): value(model_ss.reservoir[h, params.nb_day_steps])
        for h in model_ss.H
    }
    results['reservoir_level'] = reservoir_opt

    elapsed = time.time() - start
    print(f'Total time: {elapsed:.1f}s')
    return results, reservoir_opt, elapsed


def run_fansi(index: int, params: ModelParams = None, fmt: str = 'csv'):
    """Run one scenario set and save results.

    Args:
        index: Scenario set index.
        params: ModelParams (uses defaults if None).
        fmt: Output format — 'csv', 'json', 'html', or 'all'.
    """
    if params is None:
        params = ModelParams(scenarioset=index)

    print(f"{'='*10} Scenario set {index} {'='*10}")
    print(f'  Load: {params.max_load_hydro} MW, Wind cap: {params.max_wind_cap} MW')
    print(f'  Inflow scenarios: {params.num_scenarios}, Wind traces: {params.wind_scenarios}')
    print(f'  Solver: {params.solver_name}')

    results, reservoir_opt, elapsed = rolling_horizon(params)

    if fmt in ('json', 'all'):
        save_results_json(results, reservoir_opt, elapsed, params, index)
    if fmt in ('csv', 'all'):
        save_results_csv(results, reservoir_opt, params, index)
    if fmt in ('html', 'all'):
        save_results_html(results, reservoir_opt, elapsed, params, index)

    return results, elapsed


def main(argv=None):
    """Command-line entry point for module and installed-script execution."""
    parser = argparse.ArgumentParser(
        description='Fansi rolling-horizon hydro-thermal scheduler')
    parser.add_argument('index', type=int, nargs='?', help='Scenario set index (overrides config)')
    parser.add_argument('--config', help='JSON configuration exported by index.html')
    parser.add_argument('--json', action='store_true', help='Save as JSON')
    parser.add_argument('--html', action='store_true', help='Save as HTML report')
    parser.add_argument('--all', action='store_true', help='Save all formats (CSV+JSON+HTML)')
    parser.add_argument('--load', type=float, help='Max load [MW] (overrides config)')
    parser.add_argument('--wind', type=float, help='Wind capacity [MW] (overrides config)')
    parser.add_argument('--scenarios', type=int, help='Number of inflow scenarios (overrides config)')
    parser.add_argument('--wind-scenarios', type=int, help='Number of wind traces (overrides config)')
    parser.add_argument('--solver', help='Pyomo solver name (overrides config)')

    args = parser.parse_args(argv)

    if args.all:
        fmt = 'all'
    elif args.html:
        fmt = 'html'
    elif args.json:
        fmt = 'json'
    else:
        fmt = 'csv'

    params = ModelParams.from_json(args.config) if args.config else ModelParams()
    overrides = {
        'max_load_hydro': args.load,
        'max_wind_cap': args.wind,
        'num_scenarios': args.scenarios,
        'wind_scenarios': args.wind_scenarios,
        'solver_name': args.solver,
    }
    for name, override in overrides.items():
        if override is not None:
            setattr(params, name, override)

    index = args.index if args.index is not None else params.scenarioset
    params.scenarioset = index
    run_fansi(index, params, fmt=fmt)


if __name__ == '__main__':
    main()
