"""Turn the API's `start` / `finish` inputs into coordinates.

Accepted forms, cheapest first:
  1. "lat,lng"            -> parsed locally
  2. "City, ST"           -> offline gazetteer (no network)
  3. any other US address -> Nominatim (OpenStreetMap), only as a fallback
"""
import re
from dataclasses import dataclass

import requests
from django.conf import settings

from . import gazetteer

_LATLNG = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_CITY_ST = re.compile(r"^\s*([A-Za-z .'\-]+?)\s*,\s*([A-Za-z]{2})\s*(?:,?\s*(?:USA|US))?\s*$")

# Rough bounding box of the contiguous United States.
US_BOUNDS = (24.0, 49.6, -125.0, -66.5)


class GeocodeError(ValueError):
    pass


@dataclass(frozen=True)
class Place:
    query: str
    lat: float
    lng: float
    label: str

    def in_us(self):
        s, n, w, e = US_BOUNDS
        return s <= self.lat <= n and w <= self.lng <= e


def geocode(text: str) -> Place:
    text = (text or "").strip()
    if not text:
        raise GeocodeError("Location is empty.")

    if m := _LATLNG.match(text):
        place = Place(text, float(m[1]), float(m[2]), f"{m[1]}, {m[2]}")
    elif (m := _CITY_ST.match(text)) and (pt := gazetteer.lookup(m[1], m[2])):
        place = Place(text, pt[0], pt[1], f"{m[1].title()}, {m[2].upper()}")
    else:
        place = _nominatim(text)

    if not place.in_us():
        raise GeocodeError(f"'{text}' is not within the contiguous USA.")
    return place


def _nominatim(text: str) -> Place:
    try:
        r = requests.get(
            settings.NOMINATIM_URL,
            params={"q": text, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            timeout=settings.EXTERNAL_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise GeocodeError(f"Could not geocode '{text}' (geocoder unavailable).") from exc
    if not data:
        raise GeocodeError(f"Could not find '{text}' in the USA.")
    return Place(text, float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"])
