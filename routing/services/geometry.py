import numpy as np

EARTH_RADIUS_MI = 3958.8


def haversine_mi(lat1, lng1, lat2, lng2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lng2) - np.radians(lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(a))


def to_unit_xyz(lat, lng):
    """Lat/lng (degrees) -> points on the unit sphere, for KD-tree chord distance."""
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lng, float))
    return np.column_stack((np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)))


def chord_to_miles(chord):
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.clip(chord, 0, 2) / 2)


def miles_to_chord(miles):
    return 2 * np.sin(miles / (2 * EARTH_RADIUS_MI))
