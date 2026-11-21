"""
app/utils/geo.py
────────────────
Haversine great-circle distance between two lat/lng coordinates.
No external API required.
"""

import math


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the distance in kilometres between two points on Earth."""
    R = 6371.0  # Earth radius in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
