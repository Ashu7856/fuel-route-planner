"""Find stations near a route and choose the cheapest fuel-up plan.

Pipeline (all in-memory, no extra network calls):
  1. cumulative mileage along the route polyline
  2. KD-tree: snap every station to its nearest route vertex; keep those within
     `corridor_mi` of the route -> each gets a "mile marker" along the route
  3. greedy "gas station problem" solver, optimal for continuous purchases:
       - at each stop, if a cheaper station is reachable on a full tank, buy only
         enough to get there;
       - otherwise fill up, and move on to the cheapest reachable station.
"""
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .geometry import chord_to_miles, haversine_mi, miles_to_chord, to_unit_xyz
from .stations import get_index


class InfeasibleRoute(ValueError):
    pass


@dataclass
class Candidate:
    station_id: int
    mile: float
    price: float
    offroute_mi: float


@dataclass
class Stop:
    station_id: int
    mile: float
    price: float
    offroute_mi: float
    gallons: float
    cost: float


@dataclass
class Plan:
    stops: list[Stop]
    total_cost: float
    gallons_purchased: float
    gallons_needed: float


def cumulative_miles(coords: np.ndarray, total_mi: float) -> np.ndarray:
    seg = haversine_mi(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    if cum[-1] > 0:  # reconcile with the routing engine's own distance
        cum *= total_mi / cum[-1]
    return cum


def find_candidates(coords: np.ndarray, cum: np.ndarray, corridor_mi: float) -> list[Candidate]:
    idx = get_index()
    if idx.ids.size == 0:
        return []
    tree = cKDTree(to_unit_xyz(coords[:, 0], coords[:, 1]))
    dist, nearest = tree.query(
        to_unit_xyz(idx.lat, idx.lng), distance_upper_bound=miles_to_chord(corridor_mi)
    )
    keep = np.isfinite(dist)
    miles = chord_to_miles(dist[keep])
    out = [
        Candidate(int(i), float(cum[n]), float(p), float(m))
        for i, n, p, m in zip(idx.ids[keep], nearest[keep], idx.price[keep], miles)
    ]
    out.sort(key=lambda c: c.mile)
    return out


def plan_fuel_stops(
    candidates: list[Candidate], total_mi: float, *,
    range_mi: float = 500.0, mpg: float = 10.0, initial_fuel_mi: float | None = None,
) -> Plan:
    f = range_mi if initial_fuel_mi is None else min(initial_fuel_mi, range_mi)

    # Node 0 = start (free initial fuel, cannot buy), last = finish (cheaper than anything,
    # so a reachable destination always ends the search).
    miles = [0.0] + [c.mile for c in candidates] + [total_mi]
    prices = [0.0] + [c.price for c in candidates] + [-1.0]
    n = len(miles)
    last = n - 1

    stops: list[Stop] = []
    i = 0
    while i != last:
        # From the origin we can only use the fuel we start with; elsewhere a full tank.
        reach_mi = f if i == 0 else range_mi
        reach = i + 1
        while reach < n and miles[reach] - miles[i] <= reach_mi + 1e-9:
            reach += 1
        window = range(i + 1, reach)
        if not window:
            raise InfeasibleRoute(
                f"No fuel station within {reach_mi:.0f} miles after mile {miles[i]:.0f} of the route."
            )

        nxt = next((j for j in window if prices[j] < prices[i]), None)
        if nxt is not None:
            buy = max(0.0, miles[nxt] - miles[i] - f)
        else:  # nothing cheaper in range: fill up, then hop to the cheapest reachable stop
            nxt = min(window, key=lambda j: (prices[j], -miles[j]))
            buy = range_mi - f

        if i == 0:
            buy = 0.0
        elif buy > 1e-9:
            c = candidates[i - 1]
            gal = buy / mpg
            stops.append(Stop(c.station_id, miles[i], prices[i], c.offroute_mi, gal, gal * prices[i]))
        f = f + buy - (miles[nxt] - miles[i])
        i = nxt

    return Plan(
        stops=stops,
        total_cost=sum(s.cost for s in stops),
        gallons_purchased=sum(s.gallons for s in stops),
        gallons_needed=total_mi / mpg,
    )
