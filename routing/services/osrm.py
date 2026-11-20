"""Single call to the free OSRM routing API (no key required)."""
from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

METERS_PER_MILE = 1609.344


class RoutingError(RuntimeError):
    pass


@dataclass
class Route:
    coords: np.ndarray  # (N, 2) array of [lat, lng]
    distance_mi: float
    duration_min: float


def fetch_route(start, finish) -> Route:
    url = (f"{settings.OSRM_URL}/route/v1/driving/"
           f"{start.lng:.6f},{start.lat:.6f};{finish.lng:.6f},{finish.lat:.6f}")
    try:
        r = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            timeout=settings.EXTERNAL_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError("Routing service is unavailable.") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(f"No drivable route found ({data.get('code', 'unknown')}).")
    route = data["routes"][0]
    lnglat = np.asarray(route["geometry"]["coordinates"], dtype=float)
    return Route(
        coords=lnglat[:, ::-1].copy(),
        distance_mi=route["distance"] / METERS_PER_MILE,
        duration_min=route["duration"] / 60,
    )
