"""In-memory station index (numpy arrays), loaded once per process."""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from routing.models import FuelStation


@dataclass
class StationIndex:
    ids: np.ndarray
    lat: np.ndarray
    lng: np.ndarray
    price: np.ndarray


@lru_cache(maxsize=1)
def get_index() -> StationIndex:
    rows = list(FuelStation.objects.values_list("id", "lat", "lng", "price"))
    if not rows:
        return StationIndex(*(np.array([]) for _ in range(4)))
    a = np.array([(i, la, lo, float(p)) for i, la, lo, p in rows])
    return StationIndex(a[:, 0].astype(int), a[:, 1], a[:, 2], a[:, 3])


def clear_index():
    get_index.cache_clear()
