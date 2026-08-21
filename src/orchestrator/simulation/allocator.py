"""
Vectorised allocation solver — the numeric core of the Monte Carlo engine.

Replaces the per-iteration CBC subprocess call that used to dominate runtime.
The routing LP has a special structure:

    minimise   sum_i x_i * c_i
    subject to sum_i x_i        == D          (demand)
               0 <= x_i <= cap_i              (capacity)
               sum_i x_i * e_i >= E * D       (ESG floor, optional)

With only the demand and box constraints it is a continuous knapsack: fill the
cheapest suppliers first. Adding the single ESG row makes it a parametric LP,
solved here by Lagrangian relaxation on that row:

    L(lambda) = minimise sum_i x_i * (c_i - lambda * e_i)   s.t. demand + box

L(lambda) is again a greedy fill, and the ESG of its solution is monotonically
non-decreasing in lambda. Bisect to the critical lambda*, then interpolate
between the solutions bracketing it. Both bracket solutions are optimal for
L(lambda*), so their convex combination that meets the ESG row with equality is
the exact LP optimum — not an approximation.

Every step is batched across all Monte Carlo iterations at once, so 1,000
iterations cost roughly the same as one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_BISECTION_STEPS = 48
_LAMBDA_GROWTH_STEPS = 40


@dataclass
class BatchAllocation:
    """Result of solving a whole Monte Carlo batch at once.

    All arrays have leading dimension ``n_iterations``.
    """

    allocation: np.ndarray      # (M, n) units per supplier
    total_cost: np.ndarray      # (M,)
    feasible: np.ndarray        # (M,) bool
    esg_score: np.ndarray       # (M,) demand-weighted portfolio ESG

    def __len__(self) -> int:
        return int(self.allocation.shape[0])


def greedy_fill(cost: np.ndarray, capacity: np.ndarray, demand: np.ndarray) -> np.ndarray:
    """Continuous-knapsack fill, batched.

    Args:
        cost: (M, n) effective landed cost per unit. Lower is filled first.
        capacity: (M, n) available units per supplier.
        demand: (M,) units to source.

    Returns:
        (M, n) allocation. Rows where total capacity < demand are filled to
        capacity; use :func:`is_feasible` to detect them.
    """
    order = np.argsort(cost, axis=1, kind="stable")
    cap_sorted = np.take_along_axis(capacity, order, axis=1)

    filled_before = np.cumsum(cap_sorted, axis=1) - cap_sorted
    room = demand[:, None] - filled_before
    alloc_sorted = np.clip(room, 0.0, cap_sorted)

    allocation = np.empty_like(alloc_sorted)
    np.put_along_axis(allocation, order, alloc_sorted, axis=1)
    return allocation


def is_feasible(capacity: np.ndarray, demand: np.ndarray) -> np.ndarray:
    """(M,) bool — whether total capacity can cover demand."""
    return capacity.sum(axis=1) >= demand - 1e-6


def solve_batch(
    cost: np.ndarray,
    capacity: np.ndarray,
    esg: np.ndarray,
    demand: np.ndarray,
    min_esg_score: float = 0.0,
) -> BatchAllocation:
    """Solve the routing LP for an entire Monte Carlo batch.

    Args:
        cost: (M, n) effective landed cost per unit.
        capacity: (M, n) supplier capacity in units.
        esg: (n,) or (M, n) supplier ESG scores on a 0-100 scale.
        demand: (M,) units required per iteration.
        min_esg_score: portfolio ESG floor. 0 disables the constraint.

    Returns:
        A :class:`BatchAllocation`. Iterations that cannot meet demand — or that
        cannot reach the ESG floor even at full capacity — are marked infeasible.
    """
    cost = np.asarray(cost, dtype=float)
    capacity = np.asarray(capacity, dtype=float)
    demand = np.asarray(demand, dtype=float)
    esg = np.asarray(esg, dtype=float)
    if esg.ndim == 1:
        esg = np.broadcast_to(esg, cost.shape)

    feasible = is_feasible(capacity, demand)

    if min_esg_score <= 0:
        allocation = greedy_fill(cost, capacity, demand)
        return _finalise(allocation, cost, esg, demand, feasible)

    # An ESG floor is active: bisect the Lagrange multiplier on the ESG row.
    target = min_esg_score * demand

    lam_lo = np.zeros_like(demand)
    alloc_lo = greedy_fill(cost, capacity, demand)
    esg_lo = _weighted_esg(alloc_lo, esg)

    # Grow an upper bracket until the ESG row is satisfied (or we give up).
    lam_hi = np.where(esg_lo < target, 1.0, 0.0)
    alloc_hi = alloc_lo.copy()
    esg_hi = esg_lo.copy()
    unmet = esg_lo < target - 1e-9

    for _ in range(_LAMBDA_GROWTH_STEPS):
        if not unmet.any():
            break
        alloc_try = greedy_fill(cost - lam_hi[:, None] * esg, capacity, demand)
        esg_try = _weighted_esg(alloc_try, esg)
        newly_met = unmet & (esg_try >= target - 1e-9)
        alloc_hi[newly_met] = alloc_try[newly_met]
        esg_hi[newly_met] = esg_try[newly_met]
        unmet = unmet & ~newly_met
        lam_hi = np.where(unmet, lam_hi * 2.0, lam_hi)

    # Rows still unmet cannot reach the ESG floor at any price.
    feasible = feasible & ~unmet

    for _ in range(_BISECTION_STEPS):
        lam_mid = 0.5 * (lam_lo + lam_hi)
        alloc_mid = greedy_fill(cost - lam_mid[:, None] * esg, capacity, demand)
        esg_mid = _weighted_esg(alloc_mid, esg)
        meets = esg_mid >= target - 1e-9

        lam_hi = np.where(meets, lam_mid, lam_hi)
        alloc_hi = np.where(meets[:, None], alloc_mid, alloc_hi)
        esg_hi = np.where(meets, esg_mid, esg_hi)

        lam_lo = np.where(meets, lam_lo, lam_mid)
        alloc_lo = np.where(meets[:, None], alloc_lo, alloc_mid)
        esg_lo = np.where(meets, esg_lo, esg_mid)

    # Interpolate across the critical lambda so the ESG row binds exactly.
    span = esg_hi - esg_lo
    theta = np.where(span > 1e-9, (target - esg_lo) / np.where(span > 1e-9, span, 1.0), 1.0)
    theta = np.clip(theta, 0.0, 1.0)
    # Rows already meeting the floor without any pressure keep the cheap solution.
    theta = np.where(esg_lo >= target - 1e-9, 0.0, theta)

    allocation = alloc_lo + theta[:, None] * (alloc_hi - alloc_lo)
    return _finalise(allocation, cost, esg, demand, feasible)


def _weighted_esg(allocation: np.ndarray, esg: np.ndarray) -> np.ndarray:
    """(M,) sum of allocated units times ESG — comparable against ``score * demand``."""
    return np.einsum("ij,ij->i", allocation, esg)


def _finalise(
    allocation: np.ndarray,
    cost: np.ndarray,
    esg: np.ndarray,
    demand: np.ndarray,
    feasible: np.ndarray,
) -> BatchAllocation:
    units = allocation.sum(axis=1)
    safe_units = np.where(units > 1e-9, units, 1.0)
    return BatchAllocation(
        allocation=allocation,
        total_cost=np.einsum("ij,ij->i", allocation, cost),
        feasible=feasible,
        esg_score=_weighted_esg(allocation, esg) / safe_units,
    )


def weighted_average(allocation: np.ndarray, per_supplier: np.ndarray) -> np.ndarray:
    """(M,) allocation-weighted mean of a (M, n) or (n,) per-supplier quantity."""
    per_supplier = np.asarray(per_supplier, dtype=float)
    if per_supplier.ndim == 1:
        per_supplier = np.broadcast_to(per_supplier, allocation.shape)
    units = allocation.sum(axis=1)
    safe_units = np.where(units > 1e-9, units, 1.0)
    return np.einsum("ij,ij->i", allocation, per_supplier) / safe_units
