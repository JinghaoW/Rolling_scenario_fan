"""Benders decomposition solver for the two-stage stochastic hydro-thermal model.

Contains the critical Benders cut formula (fixed from original sign error).
"""

from pyomo.environ import Suffix, value
from pyomo.opt import SolverFactory

from c.config import ModelParams, MODULE_RANGE
from c.model import build_first_stage, build_second_stage


def _get_solver(params: ModelParams):
    """Initialize the LP solver."""
    opt = SolverFactory(params.solver_name)
    if not opt.available():
        raise RuntimeError(f"Solver '{params.solver_name}' not available")
    return opt


def solve_scenarios(params: ModelParams, topology: dict, opt,
                    load_data_ss: dict, wind_data_ss: dict,
                    initial_res: dict, inflow_ss: dict):
    """Solve all second-stage scenarios in parallel (conceptually — runs sequentially).

    Returns:
        lam_cut: {(scen_cut): {(h, k): dual_value}} — reservoir balance duals.
        obj_scen: {(scen_cut): objective_value} — scenario objectives.
        last_model: The last solved scenario model (for result extraction).
    """
    lam_cut = {}
    obj_scen = {}
    last_model = None

    for scen_in in range(1, params.num_scenarios + 1):
        for wind_s in range(1, params.wind_scenarios + 1):
            model_ss = build_second_stage(
                params, topology,
                pr_scenario=params.scenario_probability[scen_in],
                load_data_ss=load_data_ss,
                wind_data_ss=wind_data_ss,
                initial_res=initial_res,
                inflow_ss=inflow_ss,
                scen_in=scen_in,
                scen_wind=wind_s,
            )
            model_ss.dual = Suffix(direction=Suffix.IMPORT)
            opt.solve(model_ss, load_solutions=True)

            cut_idx = (scen_in - 1) * params.wind_scenarios + wind_s
            lam_cut[cut_idx] = {
                (h, k): model_ss.dual[model_ss.ReservoirBalance[h, k]]
                for h in model_ss.H for k in model_ss.K
            }
            obj_scen[cut_idx] = value(model_ss.OBJ)
            last_model = model_ss

    return lam_cut, obj_scen, last_model


def benders_iteration(params: ModelParams, topology: dict, batch: int,
                      load_data_fs: dict, load_data_ss: dict,
                      inflow_fs: dict, wind_data_fs: dict,
                      wind_data_ss: dict, inflow_ss: dict,
                      initial_reservoir: dict, reservoir_opt: dict):
    """Run Benders iterations for one day of the rolling horizon.

    Iterates between first-stage (day-ahead) and second-stage (scenarios)
    until reservoir convergence < params.benders_tol.

    Args:
        batch: Current day index (1-based). batch=1 uses initial_reservoir,
               batch>1 uses reservoir_opt[batch-1].
        reservoir_opt: Dict of previous days' reservoir levels {day: {(mod): val}}.

    Returns:
        system_log: Dict with keys 'lam_i', 'Reservoir_ss', 'Obj_ss'.
        num_iter: Number of Benders iterations performed.
        model_fs: Final first-stage model (with solution).
        model_ss: Last second-stage model.
    """
    opt = _get_solver(params)
    scen_total = params.num_scenarios * params.wind_scenarios

    lam_i = {}
    reservoir_ss = {}
    obj_ss = {}

    deviation = float('inf')
    iteration = 0

    while deviation >= params.benders_tol and iteration < params.max_benders_iter:

        # --- Build first stage ---
        if batch == 1:
            res_fs = {str(m): initial_reservoir[str(m)] for m in MODULE_RANGE}
        else:
            res_fs = {str(m): reservoir_opt[batch - 1][str(m)] for m in MODULE_RANGE}

        model_fs = build_first_stage(
            params, topology, batch,
            inflow_fs=inflow_fs, wind_data_fs=wind_data_fs,
            load_data_fs=load_data_fs, res_prev=res_fs,
            initial_reservoir=initial_reservoir,
        )

        # --- Add Benders cuts from previous iterations ---
        for i in range(iteration):
            # FIXED: Correct Benders cut formula.
            # Original had: - Σ λ * (V + V̄)  which gave wrong gradient sign.
            # Correct:  α ≥ Σ_scen [ Obj_scen + Σ_h λ_scen,h * (V_h - V̄_scen,h) ]
            # λ = ∂Obj_RT/∂V_initial (negative → more water reduces future cost).
            model_fs.Cuts.add(
                expr=model_fs.a >= sum(
                    obj_ss[i][scen] + sum(
                        lam_i[i][scen][h, 1] * (model_fs.reservoir[h, 1] - reservoir_ss[i][h])
                        for h in model_fs.H
                    )
                    for scen in range(1, scen_total + 1)
                )
            )

        # --- Solve first stage ---
        model_fs.dual = Suffix(direction=Suffix.IMPORT)
        opt.solve(model_fs, load_solutions=True)

        # First stage has only k=1 (day-ahead); grab end-of-day reservoir
        rt_reservoir = {
            mod: model_fs.reservoir[mod, 1].value
            for mod in model_fs.H
        }

        # --- Solve second stage (all scenarios) ---
        lam_cut, obj_scen, model_ss = solve_scenarios(
            params, topology, opt,
            load_data_ss=load_data_ss, wind_data_ss=wind_data_ss,
            initial_res=rt_reservoir, inflow_ss=inflow_ss,
        )

        lam_i[iteration] = lam_cut
        reservoir_ss[iteration] = rt_reservoir
        obj_ss[iteration] = obj_scen

        # --- Check convergence (per-module, avoid cross-module cancellation) ---
        if iteration > 0:
            deviation = sum(abs(
                value(model_fs.reservoir[h, 1]) - reservoir_ss[iteration - 1][h]
            ) for h in model_fs.H)

        print(f'  Benders iter {iteration}: FS obj={value(model_fs.OBJ):.2f}, '
              f'SS obj={value(model_ss.OBJ):.4f}, error={deviation:.6f}')

        iteration += 1

    return (
        {'lam_i': lam_i, 'Reservoir_ss': reservoir_ss, 'Obj_ss': obj_ss},
        iteration, model_fs, model_ss,
    )
