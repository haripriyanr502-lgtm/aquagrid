"""Road segments covered by the digital twin (twin/ward.inp junctions).

Coordinates are APPROXIMATE centres used only to draw the segment on the map.
They are never copied onto a pothole detection as if they were its GPS position.
Verify each one on Google Maps before a demo.
"""
SEGMENTS = {
    "J1": {"name": "HSR Layout 27th Main",  "lat": 12.9121, "lng": 77.6446},
    "J2": {"name": "Silk Board Junction",   "lat": 12.9177, "lng": 77.6238},
    "J3": {"name": "BTM Layout 2nd Stage",  "lat": 12.9166, "lng": 77.6101},
    "J4": {"name": "Madiwala",              "lat": 12.9226, "lng": 77.6174},
}


def segment_name(seg):
    return SEGMENTS.get(seg, {}).get("name", seg or "unknown segment")
