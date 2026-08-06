#!/usr/bin/env python3
"""Bake map_names.json — the street-NAME lookup layer for the map HUD.

Separate from the render bake (map_data.json stays untouched): fetches every
*named* drivable way within the same 12.5 km radius of the map origin from
Overpass, projects it to the same local-metre frame, simplifies coarsely
(name lookup needs ~5 m accuracy, not render accuracy) and writes
``map_names.json`` next to ``map_data.json``. Needs internet — run on the Mac,
never on the Pi.

Usage: python3 tools/bake_map_names.py
"""

import json
import math
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "map_names.json")

# must match map_data.json / map_geometry.py
ORIGIN = (-28.970008, -51.071114)
RADIUS_M = 12500
SIMPLIFY_M = 5.0

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = f"""
[out:json][timeout:120];
way(around:{RADIUS_M},{ORIGIN[0]},{ORIGIN[1]})
  ["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service)(_link)?$"]
  ["name"];
out geom;
"""


def to_en(lat, lon):
    m_lat = 111132.95
    m_lon = 111319.49 * math.cos(math.radians(ORIGIN[0]))
    return (lon - ORIGIN[1]) * m_lon, (lat - ORIGIN[0]) * m_lat


def simplify(pts, tol):
    """Douglas-Peucker on [(e, n), ...]."""
    if len(pts) < 3:
        return pts
    ax, ay = pts[0]
    bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    dmax, imax = 0.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        if seg2 == 0.0:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d > dmax:
            dmax, imax = d, i
    if dmax <= tol:
        return [pts[0], pts[-1]]
    left = simplify(pts[:imax + 1], tol)
    right = simplify(pts[imax:], tol)
    return left[:-1] + right


def main():
    print(f"querying Overpass ({RADIUS_M/1000:.1f} km around {ORIGIN})...")
    req = urllib.request.Request(
        OVERPASS, data=QUERY.encode(),
        headers={"User-Agent": "ftcan-cluster-name-bake/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)

    roads = []
    n_pts_in = n_pts_out = 0
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        name = el.get("tags", {}).get("name", "").strip()
        if not name:
            continue
        pts = [to_en(g["lat"], g["lon"]) for g in el["geometry"]]
        n_pts_in += len(pts)
        pts = simplify(pts, SIMPLIFY_M)
        n_pts_out += len(pts)
        roads.append({"n": name,
                      "p": [[round(e, 1), round(n, 1)] for e, n in pts]})

    if not roads:
        sys.exit("no named roads returned — refusing to write an empty bake")

    out = {
        "origin": list(ORIGIN),
        "generated": time.strftime("%Y-%m-%d"),
        "source": f"Overpass, named drivable ways, r={RADIUS_M} m, "
                  f"DP {SIMPLIFY_M} m",
        "roads": roads,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    names = {r["n"] for r in roads}
    print(f"wrote {OUT}: {len(roads)} ways, {len(names)} distinct names, "
          f"{n_pts_in} -> {n_pts_out} points, "
          f"{os.path.getsize(OUT)/1024:.0f} KiB")


if __name__ == "__main__":
    main()
