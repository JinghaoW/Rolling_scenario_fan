"""Pyomo model builders for first-stage (day-ahead) and second-stage (real-time) problems."""

from pyomo.environ import (
    ConcreteModel, Set, RangeSet, Var, Param, Objective, Constraint, ConstraintList,
    NonNegativeReals, minimize,
)

from c.config import ModelParams


def _hydro_topology_params(model, topology):
    """Extract hydro topology parameters from HDF5 data into Pyomo Param dicts.

    Returns dicts ready for Param(initialize=...).
    """
    hydro = topology['hydro']
    modules = hydro['modules']

    qd_max = {}
    en_eq = {}
    for mod in modules:
        for k, seg in enumerate(hydro['nb_seg'][mod]):
            qd_max[(mod, seg)] = hydro['Qd_max'][mod][k]
            en_eq[(mod, seg)] = hydro['En_eq'][mod][k]

    qb_max = {mod: hydro['Qb_max'][mod] for mod in modules}
    qs_max = {mod: hydro['Qs_max'][mod] for mod in modules}
    p_max = {mod: hydro['P_max'][mod] for mod in modules}
    v_max = {mod: hydro['V_max'][mod] for mod in modules}

    return {
        'qd_max': qd_max, 'en_eq': en_eq,
        'qb_max': qb_max, 'qs_max': qs_max,
        'p_max': p_max, 'v_max': v_max,
        'modules': modules,
        'nb_seg': hydro['nb_seg'],
        'b_input': hydro['B_input'],
        's_input': hydro['S_input'],
        'd_input': hydro['D_input'],
    }


def _build_hydro_sets(model, hydro):
    """Attach hydro Sets to the model."""
    model.H = Set(initialize=hydro['modules'], ordered=True)
    model.Seg = Set(model.H, initialize=hydro['nb_seg'], ordered=True)
    hseg_init = {(h, s) for h in model.H for s in model.Seg[h]}
    model.HSeg = Set(dimen=2, initialize=hseg_init, ordered=True)
    model.B_input = Set(model.H, initialize=hydro['b_input'])
    model.S_input = Set(model.H, initialize=hydro['s_input'])
    model.D_input = Set(model.H, initialize=hydro['d_input'])


def _build_hydro_params(model, hydro):
    """Attach hydro Params to the model."""
    model.ResMax = Param(model.H, initialize=hydro['v_max'])
    model.Qd_max = Param(model.HSeg, initialize=hydro['qd_max'])
    model.En_eq = Param(model.HSeg, initialize=hydro['en_eq'])
    model.Qb_max = Param(model.H, initialize=hydro['qb_max'])
    model.Qs_max = Param(model.H, initialize=hydro['qs_max'])
    model.P_max = Param(model.H, initialize=hydro['p_max'])


def _reservoir_balance_term(model, h, k):
    """Common reservoir balance: sum of outflows minus sum of inflows from upstream."""
    return (
        sum(model.q_d[h, s, k] for s in model.Seg[h])
        + model.q_b[h, k] + model.q_s[h, k]
        - sum(model.q_s[str(r), k] for r in model.S_input[h])
        - sum(model.q_b[str(r), k] for r in model.B_input[h])
        - sum(model.q_d[str(r), s, k] for r in model.D_input[h] for s in model.Seg[str(r)])
    )


# ─── Variable bound helpers ───────────────────────────────────────────

def _discharge_bounds(model, h, s, k):
    return (0.0, float(model.Qd_max[h, s]))


def _bypass_bounds(model, h, k):
    return (0.0, float(model.Qb_max[h]))


def _spillage_bounds(model, h, k):
    return (0.0, float(model.Qs_max[h]))


def _production_bounds(model, h, k):
    return (0.0, float(model.P_max[h]))


def _reservoir_bounds(model, h, k):
    return (0.0, float(model.ResMax[h]))


# ═══════════════════════════════════════════════════════════════════════
#  First Stage (Day-Ahead)
# ═══════════════════════════════════════════════════════════════════════

def build_first_stage(params: ModelParams, topology: dict, batch: int,
                      inflow_fs: dict, wind_data_fs: dict, load_data_fs: dict,
                      res_prev: dict, initial_reservoir: dict):
    """Build the first-stage (day-ahead) Pyomo model.

    Args:
        params: Model parameters.
        topology: Parsed HDF5 topology dict.
        batch: Day index (1 = use InitRes, >1 = use res_prev).
        inflow_fs: Regulated/unregulated inflow for first stage {(type): {(mod, k): val}}.
        wind_data_fs: Wind capacity dict {k: val}.
        load_data_fs: Load dict {(area, k): val}.
        res_prev: Previous day reservoir {(mod): val} (used when batch > 1).
        initial_reservoir: Initial reservoir for day 1 {(mod): val}.
    """
    model = ConcreteModel('FirstStage')
    hydro = _hydro_topology_params(model, topology)

    # --- Sets ---
    model.K = RangeSet(params.nb_day_steps_da)
    model.A = Set(initialize=params.areas)
    _build_hydro_sets(model, hydro)

    # --- Params ---
    model.Load = Param(model.A, model.K, initialize=load_data_fs)
    model.Load_shedding_cost = Param(initialize=params.cost_shedding)
    model.MaxWindCap = Param(model.K, initialize=wind_data_fs)

    _build_hydro_params(model, hydro)

    if batch == 1:
        model.InitRes = Param(model.H, initialize=initial_reservoir)
    else:
        model.reservoir_DA = Param(model.H, initialize=res_prev)

    model.Ih_t = Param(model.H, model.K, initialize=inflow_fs['regulated'])
    model.Uh_t = Param(model.H, model.K, initialize=inflow_fs['unregulated'])
    model.LB = Param(initialize=-1e-6)

    # --- Variables ---
    model.wind_P = Var(model.K, within=NonNegativeReals)
    model.wind_C = Var(model.K, within=NonNegativeReals)
    model.hydro_prod = Var(model.H, model.K, bounds=_production_bounds)
    model.reservoir = Var(model.H, model.K, bounds=_reservoir_bounds)
    model.q_d = Var(model.HSeg, model.K, bounds=_discharge_bounds)
    model.q_b = Var(model.H, model.K, bounds=_bypass_bounds)
    model.q_s = Var(model.H, model.K, bounds=_spillage_bounds)
    model.load_shedding = Var(model.A, model.K, within=NonNegativeReals)
    model.a = Var(initialize=model.LB)
    model.day_ahead_cost = Var()

    # --- Constraints ---
    def power_balance_rule(model, a, k):
        return (sum(model.hydro_prod[h, k] for h in model.H)
                + model.wind_P[k] + model.load_shedding[a, k]
                == model.Load[a, k])

    model.PowerBalance = Constraint(model.A, model.K, rule=power_balance_rule)

    def wind_rule(model, k):
        return model.wind_P[k] + model.wind_C[k] == model.MaxWindCap[k]

    model.WindConstraint = Constraint(model.K, rule=wind_rule)

    def reservoir_rule(model, h, k):
        init = model.InitRes[h] if batch == 1 else model.reservoir_DA[h]
        return (model.reservoir[h, k] - init
                == params.conversion * (model.Ih_t[h, k] + model.Uh_t[h, k]
                                        - _reservoir_balance_term(model, h, k)))

    model.ReservoirBalance = Constraint(model.H, model.K, rule=reservoir_rule)

    def hydro_prod_rule(model, h, k):
        return model.hydro_prod[h, k] == sum(
            model.En_eq[h, s] * model.q_d[h, s, k] for s in model.Seg[h])

    model.HydroProd = Constraint(model.H, model.K, rule=hydro_prod_rule)

    def lb_rule(model, h, k):
        return model.reservoir[h, k] >= params.lb * model.ResMax[h]

    model.LowerBound = Constraint(model.H, model.K, rule=lb_rule)

    def alpha_lower_rule(model):
        return model.a >= model.LB

    model.AlphaLowerBound = Constraint(rule=alpha_lower_rule)

    model.Cuts = ConstraintList()

    # --- Objective ---
    def da_cost_rule(model):
        return model.day_ahead_cost == (
            sum(model.Load_shedding_cost * model.load_shedding[a, k]
                for a in model.A for k in model.K)
            + sum(params.cost_bypass * model.q_b[h, k]
                  + params.cost_spillage * model.q_s[h, k]
                  for h in model.H for k in model.K)
            + sum(params.cost_wind_curt * model.wind_C[k] for k in model.K)
        )

    model.DACost = Constraint(rule=da_cost_rule)

    def obj_rule(model):
        return model.day_ahead_cost + model.a

    model.OBJ = Objective(rule=obj_rule, sense=minimize)

    return model


# ═══════════════════════════════════════════════════════════════════════
#  Second Stage (Real-Time / Scenario)
# ═══════════════════════════════════════════════════════════════════════

def build_second_stage(params: ModelParams, topology: dict,
                       pr_scenario: float, load_data_ss: dict,
                       wind_data_ss: dict, initial_res: dict,
                       inflow_ss: dict, scen_in: int, scen_wind: int):
    """Build one second-stage scenario Pyomo model.

    Args:
        params: Model parameters.
        topology: Parsed HDF5 topology dict.
        pr_scenario: Probability weight for this scenario (1/K).
        load_data_ss: Load dict {(area, k): val} for full horizon.
        wind_data_ss: Wind traces {scen_wind: {k: val}}.
        initial_res: Starting reservoir from first stage {(mod): val}.
        inflow_ss: Inflow dict {type: {scen: {(mod, k): val}}}.
        scen_in: Inflow scenario index (1-based).
        scen_wind: Wind trace index (1-based).
    """
    model = ConcreteModel('SecondStage')
    hydro = _hydro_topology_params(model, topology)

    # --- Sets ---
    model.K = RangeSet(params.nb_day_steps)
    model.A = Set(initialize=params.areas)
    _build_hydro_sets(model, hydro)

    # --- Params ---
    model.Pr = Param(initialize=pr_scenario)
    model.Load = Param(model.A, model.K, initialize=load_data_ss)
    model.Load_shedding_cost = Param(initialize=params.cost_shedding)
    model.MaxWindCap = Param(model.K, initialize=wind_data_ss[scen_wind])
    model.reservoir_DA = Param(model.H, initialize=initial_res)

    _build_hydro_params(model, hydro)

    model.Ih_t = Param(model.H, model.K, initialize=inflow_ss['regulated'][scen_in])
    model.Uh_t = Param(model.H, model.K, initialize=inflow_ss['unregulated'][scen_in])

    # --- Variables ---
    model.wind_P = Var(model.K, within=NonNegativeReals)
    model.wind_C = Var(model.K, within=NonNegativeReals)
    model.hydro_prod = Var(model.H, model.K, bounds=_production_bounds)
    model.reservoir = Var(model.H, model.K, bounds=_reservoir_bounds)
    model.q_d = Var(model.HSeg, model.K, bounds=_discharge_bounds)
    model.q_b = Var(model.H, model.K, bounds=_bypass_bounds)
    model.q_s = Var(model.H, model.K, bounds=_spillage_bounds)
    model.load_shedding = Var(model.A, model.K, within=NonNegativeReals)

    # --- Constraints ---
    def wind_rule(model, k):
        return model.wind_P[k] + model.wind_C[k] == model.MaxWindCap[k]

    model.WindConstraint = Constraint(model.K, rule=wind_rule)

    def reservoir_rule(model, h, k):
        prev = model.reservoir_DA[h] if k == 1 else model.reservoir[h, k - 1]
        return (model.reservoir[h, k] - prev
                == params.conversion * (model.Ih_t[h, k] + model.Uh_t[h, k]
                                        - _reservoir_balance_term(model, h, k)))

    model.ReservoirBalance = Constraint(model.H, model.K, rule=reservoir_rule)

    def hydro_prod_rule(model, h, k):
        return model.hydro_prod[h, k] == sum(
            model.En_eq[h, s] * model.q_d[h, s, k] for s in model.Seg[h])

    model.HydroProd = Constraint(model.H, model.K, rule=hydro_prod_rule)

    def lb_rule(model, h, k):
        return model.reservoir[h, k] >= params.lb * model.ResMax[h]

    model.LowerBound = Constraint(model.H, model.K, rule=lb_rule)

    def power_balance_rule(model, a, k):
        return (sum(model.hydro_prod[h, k] for h in model.H)
                + model.load_shedding[a, k] + model.wind_P[k]
                == model.Load[a, k])

    model.PowerBalance = Constraint(model.A, model.K, rule=power_balance_rule)

    # --- Objective ---
    def rt_cost_rule(model):
        return model.Pr * (
            sum(model.Load_shedding_cost * model.load_shedding[a, k]
                for a in model.A for k in model.K)
            + sum(params.cost_spillage * model.q_s[h, k]
                  + params.cost_bypass * model.q_b[h, k]
                  for h in model.H for k in model.K)
            + sum(params.cost_wind_curt * model.wind_C[k] for k in model.K)
        )

    model.OBJ = Objective(rule=rt_cost_rule, sense=minimize)

    return model
