"""Offline US city -> (lat, lng) lookup, built from the bundled `zipcodes` dataset.

Used for (a) geocoding the fuel-station CSV, which has no coordinates, and
(b) resolving "City, ST" API inputs without any external geocoding call.
"""
import re
from functools import lru_cache

import zipcodes

_ABBREV = (("st ", "saint "), ("ste ", "sainte "), ("mt ", "mount "), ("ft ", "fort "))


def normalize(city: str) -> str:
    c = re.sub(r"[.']", "", city.lower()).strip()
    return re.sub(r"\s+", " ", c)


def _variants(city: str):
    c = normalize(city)
    yield c
    for short, long_ in _ABBREV:
        if c.startswith(short):
            yield long_ + c[len(short):]
        if c.startswith(long_):
            yield short + c[len(long_):]
    if " " in c:
        yield c.replace(" ", "")
    if c.startswith("n "):
        yield "north " + c[2:]
    if c.startswith("w "):
        yield "west " + c[2:]


@lru_cache(maxsize=1)
def _index():
    acc: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for z in zipcodes.list_all():
        if not z.get("active") or not z.get("lat") or not z.get("long"):
            continue
        pt = (float(z["lat"]), float(z["long"]))
        names = [z["city"], *z.get("acceptable_cities", [])]
        for n in names:
            acc.setdefault((normalize(n), z["state"]), []).append(pt)
    return {
        k: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v))
        for k, v in acc.items()
    }


def lookup(city: str, state: str):
    """Return (lat, lng) for a US city/state, or None."""
    idx = _index()
    state = state.strip().upper()
    for v in _variants(city):
        hit = idx.get((v, state))
        if hit:
            return hit
    return None
