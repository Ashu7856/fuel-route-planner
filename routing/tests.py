import itertools
import random
from unittest import mock

import numpy as np
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from routing.services import stations as station_index
from routing.services.osrm import Route
from routing.services.planner import Candidate, InfeasibleRoute, plan_fuel_stops


def brute_force_cost(cands, total, R=500.0, mpg=10.0):
    """Reference DP over a 1-mile fuel grid: min cost to reach `total` from a full tank."""
    pts = [(0.0, 0.0)] + [(c.mile, c.price) for c in cands]
    best = {}  # (station idx, fuel miles) -> cost
    import heapq
    pq = [(0.0, 0, int(R))]
    seen = {}
    while pq:
        cost, i, fuel = heapq.heappop(pq)
        if seen.get((i, fuel), 1e18) < cost - 1e-9:
            continue
        pos = pts[i][0]
        if total - pos <= fuel:
            return cost
        if i > 0 and fuel < R:  # buy 1 mile of fuel
            nc = cost + pts[i][1] / mpg
            if nc < seen.get((i, fuel + 1), 1e18):
                seen[(i, fuel + 1)] = nc
                heapq.heappush(pq, (nc, i, fuel + 1))
        for j in range(i + 1, len(pts)):
            d = pts[j][0] - pos
            if d > fuel:
                break
            nf = int(round(fuel - d))
            if cost < seen.get((j, nf), 1e18):
                seen[(j, nf)] = cost
                heapq.heappush(pq, (cost, j, nf))
    return None


class PlannerTests(TestCase):
    def test_short_trip_needs_no_stop(self):
        plan = plan_fuel_stops([Candidate(1, 100, 3.0, 1)], 300)
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0)

    def test_buys_only_enough_to_reach_cheaper_station(self):
        # 800 mi trip; station A (mile 450, $4.00), B (mile 700, $3.00)
        plan = plan_fuel_stops([Candidate(1, 450, 4.0, 0), Candidate(2, 700, 3.0, 0)], 800)
        a, b = plan.stops
        self.assertAlmostEqual(a.gallons, 20.0)   # 200 mi to reach B, 50 mi left on tank
        self.assertAlmostEqual(b.gallons, 10.0)   # just enough for last 100 mi
        self.assertAlmostEqual(plan.total_cost, 20 * 4 + 10 * 3)

    def test_gap_too_large_raises(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([Candidate(1, 100, 3.0, 0)], 900)

    def test_matches_bruteforce_on_random_routes(self):
        rng = random.Random(7)
        for _ in range(40):
            total = rng.randint(600, 2200)
            miles = sorted(rng.sample(range(5, total - 5), rng.randint(8, 25)))
            cands = [Candidate(i, float(m), round(rng.uniform(2.8, 4.2), 3), 0) for i, m in enumerate(miles)]
            try:
                plan = plan_fuel_stops(cands, float(total))
            except InfeasibleRoute:
                self.assertIsNone(brute_force_cost(cands, total))
                continue
            ref = brute_force_cost(cands, total)
            self.assertAlmostEqual(plan.total_cost, ref, delta=0.01 * max(1, len(cands)))
            # the tank never goes negative and range is never exceeded
            self.assertLessEqual(max(s.gallons for s in plan.stops) if plan.stops else 0, 50.0 + 1e-6)


def fake_route(waypoints, per_leg=400):
    pts = []
    for (a, b) in zip(waypoints[:-1], waypoints[1:]):
        for t in np.linspace(0, 1, per_leg, endpoint=False):
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    pts.append(waypoints[-1])
    coords = np.array(pts)
    from routing.services.geometry import haversine_mi
    dist = float(haversine_mi(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1]).sum()) * 1.12
    return Route(coords=coords, distance_mi=dist, duration_min=dist / 62 * 60)


# Rough LA -> NYC path along I-40 / I-40 / I-81 / I-78 city waypoints.
LA_NYC = [(34.05, -118.24), (35.2, -111.65), (35.08, -106.65), (35.22, -101.83), (35.47, -97.52),
          (36.07, -94.16), (35.15, -90.05), (36.16, -86.78), (36.0, -83.9), (37.27, -79.94),
          (39.96, -75.6), (40.71, -74.0)]


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_stations", verbosity=0)
        station_index.clear_index()

    def setUp(self):
        cache.clear()
        p = mock.patch("routing.services.trip.fetch_route", return_value=fake_route(LA_NYC))
        self.fetch = p.start()
        self.addCleanup(p.stop)

    def test_cross_country(self):
        r = self.client.get(reverse("route-plan"), {"start": "Los Angeles, CA", "finish": "New York, NY"})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertGreater(len(d["fuel_stops"]), 3)
        self.assertEqual(round(sum(s["cost"] for s in d["fuel_stops"]), 2), d["total_fuel_cost"])
        self.assertAlmostEqual(d["total_gallons_needed"], d["distance_miles"] / 10, places=1)
        # every leg between consecutive stops fits within 500 miles
        marks = [0] + [s["route_mile"] for s in d["fuel_stops"]]
        self.assertTrue(all(b - a <= 500 for a, b in zip(marks, marks[1:])))
        self.assertLessEqual(d["distance_miles"] - marks[-1], 500)
        self.assertEqual(d["map"]["features"][0]["geometry"]["type"], "LineString")

    def test_single_external_call_and_cache(self):
        q = {"start": "Los Angeles, CA", "finish": "New York, NY"}
        self.client.get(reverse("route-plan"), q)
        self.client.post(reverse("route-plan"), {**q, "mpg": 8}, content_type="application/json")
        self.assertEqual(self.fetch.call_count, 1)  # offline geocoding + route cache

    def test_validation_and_errors(self):
        self.assertEqual(self.client.get(reverse("route-plan")).status_code, 400)
        r = self.client.get(reverse("route-plan"), {"start": "51.5,-0.12", "finish": "New York, NY"})
        self.assertEqual(r.status_code, 400)  # London is outside the USA

    def test_map_page_renders(self):
        r = self.client.get(reverse("route-map"), {"start": "A, TX", "finish": "B, CA"})
        self.assertContains(r, "leaflet")
