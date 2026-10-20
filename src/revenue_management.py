"""
Revenue management for a generator rental branch (PowerLease Generators).

A linear programme (integer acceptances) decides how many 1-, 4-, 8- and
16-week rental requests to accept each week to maximise revenue, given a
fixed fleet and the units returning from earlier rentals.

    python src/revenue_management.py

Writes:
    outputs/weekly_plan.csv   optimised vs actual acceptances per week/product
    outputs/kpis.csv          revenue, load factor and ROI: actual vs optimised
"""

from pathlib import Path

import numpy as np
import pandas as pd
from pyomo.environ import (ConcreteModel, Constraint, NonNegativeIntegers,
                           NonNegativeReals, Objective, SolverFactory, Var,
                           maximize, value)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "plg_branch_2025.xlsx"
OUT = ROOT / "outputs"
PRODUCTS = ["1-WK", "4-WK", "8-WK", "16-WK"]


# ── 1. Load data (by label, not fixed cell positions) ─────────────────
def load_data(path: Path) -> dict:
    raw = pd.read_excel(path, sheet_name="Data", header=None)

    def lookup(label: str, col_offset: int = 1):
        row, col = np.argwhere(raw.astype(str).apply(lambda c: c.str.strip()).values == label)[0]
        return raw.iat[row, col + col_offset]

    fleet = int(lookup("Total number of Generators (units)"))
    initial_inv = int(lookup("Initial Inventory (units)"))
    unit_cost = float(lookup("Unit cost (£)"))
    durations = [int(x) for x in str(lookup("Durations (weeks)")).split(",")]
    actual = {
        "revenue": float(lookup("Total revenue (actual, £)")),
        "load_factor": float(lookup("Average load factor")),
        "roi": float(lookup("ROI (revenue per unit / cost)")),
    }

    # weekly table: header row has 'Week'; product blocks start at the '£/Day' columns
    header_row = int(np.argwhere(raw[0].astype(str).str.strip().values == "Week")[0][0])
    weekly = raw.iloc[header_row + 2:].reset_index(drop=True)
    weekly = weekly[pd.to_numeric(weekly[1], errors="coerce").notna()]
    price_cols = [c for c in raw.columns if str(raw.iat[header_row, c]).strip() == "£/Day"]

    open_weeks = pd.to_numeric(weekly[price_cols[0]], errors="coerce").notna()
    blocks = {}
    for name, offset in [("price", 0), ("demand", 1), ("accepted", 2), ("returns", 3)]:
        blocks[name] = weekly[[c + offset for c in price_cols]].apply(pd.to_numeric, errors="coerce")

    return dict(fleet=fleet, initial_inv=initial_inv, unit_cost=unit_cost,
                durations=durations, actual=actual, week_no=weekly[1].astype(int).values,
                week_start=pd.to_datetime(weekly[0]).values, open_weeks=open_weeks.values,
                inv_actual=pd.to_numeric(weekly[2]).values, **blocks)


# ── 2. Build and solve the model ──────────────────────────────────────
def solve(d: dict):
    open_idx = np.where(d["open_weeks"])[0]           # weeks 2–51 (weeks 1 & 52 closed)
    T, P = len(open_idx), len(d["durations"])
    price = d["price"].values[open_idx]
    demand = d["demand"].values[open_idx].astype(int)
    durations = d["durations"]

    # Units returning from rentals made BEFORE the horizon: a d-week product's
    # returns in its first d weeks can only come from pre-horizon bookings.
    ret = d["returns"].values[open_idx]
    bh_returns = [sum(ret[t, p] for p in range(P) if t < durations[p] and not np.isnan(ret[t, p]))
                  for t in range(T)]

    m = ConcreteModel()
    m.x = Var(range(T), range(P), domain=NonNegativeIntegers)   # units accepted
    m.inv = Var(range(T), domain=NonNegativeReals)               # units available at start of week

    m.revenue = Objective(
        expr=sum(m.x[t, p] * durations[p] * 7 * price[t, p] for t in range(T) for p in range(P)),
        sense=maximize)

    # cannot accept more than requested
    m.demand = Constraint(range(T), range(P), rule=lambda m, t, p: m.x[t, p] <= demand[t, p])

    # inventory balance: last week's stock - last week's acceptances + returns
    def balance(m, t):
        if t == 0:
            return m.inv[t] == d["initial_inv"] + bh_returns[t]
        returns_in = sum(m.x[t - durations[p], p] for p in range(P) if t - durations[p] >= 0)
        return m.inv[t] == m.inv[t - 1] - sum(m.x[t - 1, p] for p in range(P)) + returns_in + bh_returns[t]
    m.balance = Constraint(range(T), rule=balance)

    # cannot rent out more units than are available
    m.capacity = Constraint(range(T), rule=lambda m, t: sum(m.x[t, p] for p in range(P)) <= m.inv[t])

    solver = SolverFactory("appsi_highs")
    if not solver.available(exception_flag=False):
        solver = SolverFactory("glpk")
    solver.solve(m)

    x = np.array([[round(value(m.x[t, p])) for p in range(P)] for t in range(T)])
    inv = np.array([value(m.inv[t]) for t in range(T)])
    return open_idx, x, inv, price, demand


# ── 3. Report ─────────────────────────────────────────────────────────
def report(d, open_idx, x, inv, price, demand):
    OUT.mkdir(exist_ok=True)
    durations = np.array(d["durations"])
    accepted = d["accepted"].values[open_idx].astype(int)

    rev_opt = float((x * durations * 7 * price).sum())
    lf_opt = (d["fleet"] - inv.mean()) / d["fleet"]
    roi_opt = rev_opt / (d["fleet"] * d["unit_cost"])
    a = d["actual"]

    kpis = pd.DataFrame({
        "metric": ["Total revenue (£)", "Load factor", "ROI"],
        "actual": [a["revenue"], a["load_factor"], a["roi"]],
        "optimised": [rev_opt, lf_opt, roi_opt],
    })
    kpis["change"] = kpis.optimised - kpis.actual
    kpis.to_csv(OUT / "kpis.csv", index=False)

    rows = []
    for i, t in enumerate(open_idx):
        for p, name in enumerate(PRODUCTS):
            rows.append(dict(week=int(d["week_no"][t]), product=name, price_per_day=price[i, p],
                             demand=demand[i, p], accepted_actual=accepted[i, p],
                             accepted_optimised=x[i, p]))
    pd.DataFrame(rows).to_csv(OUT / "weekly_plan.csv", index=False)

    print(kpis.round(3).to_string(index=False))
    print(f"\nShare of requests accepted: actual {accepted.sum() / demand.sum():.1%}, "
          f"optimised {x.sum() / demand.sum():.1%}")


if __name__ == "__main__":
    data = load_data(DATA)
    report(data, *solve(data))
