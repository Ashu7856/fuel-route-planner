"""Orchestrates geocode -> route (1 external call, cached) -> plan -> response payload."""
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.core.cache import cache

from routing.models import FuelStation

from .geocode import geocode
from .osrm import fetch_route
from .planner import cumulative_miles, find_candidates, plan_fuel_stops

MAX_GEOMETRY_POINTS = 1500


@dataclass
class TripParams:
    start: str
    finish: str
    range_mi: float = 500.0
    mpg: float = 10.0
    corridor_mi: float = 10.0
    initial_fuel_mi: float | None = None  # None -> full tank


def _cached_route(start, finish):
    key = "route:%.4f,%.4f:%.4f,%.4f" % (start.lat, start.lng, finish.lat, finish.lng)
    route = cache.get(key)
    cached = route is not None
    if not cached:
        route = fetch_route(start, finish)
        cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
    return route, cached


def _downsample(coords: np.ndarray) -> np.ndarray:
    if len(coords) <= MAX_GEOMETRY_POINTS:
        return coords
    idx = np.linspace(0, len(coords) - 1, MAX_GEOMETRY_POINTS).round().astype(int)
    return coords[idx]


def _point(place_or_obj, lat, lng, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": props}


def plan_trip(p: TripParams) -> dict:
    start, finish = geocode(p.start), geocode(p.finish)
    route, cached = _cached_route(start, finish)

    cum = cumulative_miles(route.coords, route.distance_mi)
    candidates = find_candidates(route.coords, cum, p.corridor_mi)
    plan = plan_fuel_stops(
        candidates, route.distance_mi, range_mi=p.range_mi, mpg=p.mpg,
        initial_fuel_mi=p.initial_fuel_mi,
    )

    stations = FuelStation.objects.in_bulk([s.station_id for s in plan.stops])
    stops_out = []
    for n, s in enumerate(plan.stops, 1):
        st = stations[s.station_id]
        stops_out.append({
            "stop": n,
            "station": st.name, "address": st.address, "city": st.city, "state": st.state,
            "location": {"lat": st.lat, "lng": st.lng},
            "route_mile": round(s.mile, 1),
            "miles_off_route": round(s.offroute_mi, 1),
            "price_per_gallon": round(s.price, 3),
            "gallons_purchased": round(s.gallons, 2),
            "cost": round(s.cost, 2),
        })

    line = _downsample(route.coords)
    line_lnglat = [[round(float(lo), 5), round(float(la), 5)] for la, lo in line]
    features = [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": line_lnglat},
         "properties": {"kind": "route", "distance_miles": round(route.distance_mi, 1)}},
        _point(None, start.lat, start.lng, kind="start", label=start.label),
        _point(None, finish.lat, finish.lng, kind="finish", label=finish.label),
        *(_point(None, o["location"]["lat"], o["location"]["lng"], kind="fuel_stop",
                 **{k: o[k] for k in ("stop", "station", "city", "state", "price_per_gallon",
                                      "gallons_purchased", "cost", "route_mile")})
          for o in stops_out),
    ]

    return {
        "start": {"query": start.query, "label": start.label, "lat": start.lat, "lng": start.lng},
        "finish": {"query": finish.query, "label": finish.label, "lat": finish.lat, "lng": finish.lng},
        "distance_miles": round(route.distance_mi, 1),
        "duration_hours": round(route.duration_min / 60, 2),
        "assumptions": {
            "vehicle_range_miles": p.range_mi,
            "miles_per_gallon": p.mpg,
            "starting_fuel_miles": p.range_mi if p.initial_fuel_mi is None else p.initial_fuel_mi,
            "corridor_miles": p.corridor_mi,
            "note": ("Trip starts with the initial tank (not billed); total_fuel_cost covers "
                     "fuel bought at the listed stops. Stations are positioned at their city centre."),
        },
        "fuel_stops": stops_out,
        "total_gallons_needed": round(plan.gallons_needed, 2),
        "total_gallons_purchased": round(plan.gallons_purchased, 2),
        "total_fuel_cost": round(plan.total_cost, 2),
        "candidate_stations_considered": len(candidates),
        "route_cached": cached,
        "map": {"type": "FeatureCollection", "features": features},
    }
