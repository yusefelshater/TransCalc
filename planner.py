"""
Planner module: fetch facilities from OpenStreetMap (Overpass API),
score candidates, suggest new asphalt plant sites, and render a Folium map.

This module intentionally keeps dependencies light (requests, folium) and
implements simple geodesic helpers to avoid heavy GIS stacks. Distances are
approximate using haversine formula. Land availability is heuristically
estimated by querying nearby buildings density.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import List, Tuple, Dict, Any

import requests

try:
    import folium
except Exception:  # pragma: no cover
    folium = None  # type: ignore

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Additional public Overpass endpoints (fallbacks)
OVERPASS_URLS = [
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

# Environment helpers for configurability
def _env_bool(name: str, default: bool = False) -> bool:
    try:
        v = os.environ.get(name)
        if v is None:
            return default
        return str(v).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_backoff(name: str, default: list[int]) -> list[int]:
    try:
        v = os.environ.get(name)
        if not v:
            return default
        parts = [p.strip() for p in v.split(',') if p.strip()]
        vals = []
        for p in parts:
            try:
                vals.append(int(p))
            except Exception:
                continue
        return vals or default
    except Exception:
        return default

# Default weights per user spec
DEFAULT_WEIGHTS = {
    "road_proximity": 5.0,
    "midpoint_preference": 4.0,
    "quarry_proximity": 2.0,
    "rubber_proximity": 1.0,
    # New: weight for landuse suitability from OSM (0..1)
    "landuse_preference": 3.0,
    # New layers
    "highway_proximity": 2.5,          # proximity to major highways (motorway/trunk)
    "bitumen_source_proximity": 1.0,   # proximity to bitumen sources (if present in OSM)
}

# Search radii (meters)
SEARCH_RADIUS_M = 200000  # 200 km around path
NEAR_ROAD_MAX_M = 2000   # within 2 km considered near road

# Fallback facilities file (optional). If present, we will integrate its points.
FALLBACK_FILE = os.path.join(os.path.dirname(__file__), "fallback_facilities.json")


# -------------------------- Helpers --------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in meters between two lat/lon points."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def path_bbox(path: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    lats = [p[0] for p in path]
    lons = [p[1] for p in path]
    return min(lats), min(lons), max(lats), max(lons)


def point_to_segment_distance_m(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Approximate point-to-segment distance in meters using lat/lon projected locally.
    Uses equirectangular approximation around segment midpoint for speed.
    """
    lat1, lon1 = a
    lat2, lon2 = b
    latp, lonp = p
    lat0 = math.radians((lat1 + lat2) / 2.0)
    # meters per degree approx
    m_per_deg_lat = 111132.92 - 559.82*math.cos(2*lat0) + 1.175*math.cos(4*lat0)
    m_per_deg_lon = 111412.84*math.cos(lat0) - 93.5*math.cos(3*lat0)

    ax, ay = (lon1 * m_per_deg_lon, lat1 * m_per_deg_lat)
    bx, by = (lon2 * m_per_deg_lon, lat2 * m_per_deg_lat)
    px, py = (lonp * m_per_deg_lon, latp * m_per_deg_lat)

    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    seg_len2 = vx*vx + vy*vy
    if seg_len2 <= 1e-9:
        dx, dy = px - ax, py - ay
        return math.hypot(dx, dy)
    t = max(0.0, min(1.0, (wx*vx + wy*vy) / seg_len2))
    cx, cy = ax + t*vx, ay + t*vy
    return math.hypot(px - cx, py - cy)


def min_distance_to_path_m(point: Tuple[float, float], path: List[Tuple[float, float]]) -> float:
    dmin = float("inf")
    for i in range(len(path) - 1):
        d = point_to_segment_distance_m(point, path[i], path[i+1])
        if d < dmin:
            dmin = d
    return dmin


def path_midpoint(path: List[Tuple[float, float]]) -> Tuple[float, float]:
    # True midpoint by distance along the path (length-weighted)
    if not path:
        return (0.0, 0.0)
    if len(path) < 2:
        return path[0]
    cd = _path_cumdist_m(path)
    total = cd[-1]
    if total <= 1e-9:
        return path[len(path)//2]
    target = 0.5 * total
    # Find the segment where the target distance lies and interpolate
    for i in range(1, len(path)):
        if cd[i] >= target:
            prev = path[i-1]
            curr = path[i]
            seg_len = cd[i] - cd[i-1]
            if seg_len <= 1e-9:
                return curr
            t = (target - cd[i-1]) / seg_len
            lat = prev[0] + t * (curr[0] - prev[0])
            lon = prev[1] + t * (curr[1] - prev[1])
            return (lat, lon)
    return path[-1]


def point_at_distance_m(path: List[Tuple[float, float]], s: float) -> Tuple[float, float]:
    """Return the point on the path located at distance s meters from the start.
    If s <= 0 returns the start; if s >= total length returns the end.
    """
    if not path:
        return (0.0, 0.0)
    if len(path) < 2:
        return path[0]
    cd = _path_cumdist_m(path)
    total = cd[-1]
    if total <= 1e-9:
        return path[0]
    if s <= 0.0:
        return path[0]
    if s >= total:
        return path[-1]
    for i in range(1, len(path)):
        if cd[i] >= s:
            prev = path[i-1]
            curr = path[i]
            seg_len = cd[i] - cd[i-1]
            if seg_len <= 1e-9:
                return curr
            t = (s - cd[i-1]) / seg_len
            lat = prev[0] + t * (curr[0] - prev[0])
            lon = prev[1] + t * (curr[1] - prev[1])
            return (lat, lon)
    return path[-1]

def path_fraction_at_point(point: Tuple[float, float], path: List[Tuple[float, float]]) -> float:
    """Approximate the fractional position [0,1] along the path for the nearest
    projection of the point onto the path polyline (by segment).
    Uses the same local equirectangular projection as point_to_segment_distance_m.
    Returns 0.5 if path too short or in case of numeric issues.
    """
    if not path or len(path) < 2:
        return 0.5
    cd = _path_cumdist_m(path)
    total = cd[-1] if cd else 0.0
    if total <= 1e-9:
        return 0.5

    best_d = float("inf")
    best_s = None
    for i in range(len(path) - 1):
        a = path[i]
        b = path[i+1]
        lat1, lon1 = a
        lat2, lon2 = b
        latp, lonp = point
        lat0 = math.radians((lat1 + lat2) / 2.0)
        # meters per degree approx (same as in point_to_segment_distance_m)
        m_per_deg_lat = 111132.92 - 559.82*math.cos(2*lat0) + 1.175*math.cos(4*lat0)
        m_per_deg_lon = 111412.84*math.cos(lat0) - 93.5*math.cos(3*lat0)

        ax, ay = (lon1 * m_per_deg_lon, lat1 * m_per_deg_lat)
        bx, by = (lon2 * m_per_deg_lon, lat2 * m_per_deg_lat)
        px, py = (lonp * m_per_deg_lon, latp * m_per_deg_lat)

        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        seg_len2 = vx*vx + vy*vy
        if seg_len2 <= 1e-9:
            # Treat as a point
            dx, dy = px - ax, py - ay
            d = math.hypot(dx, dy)
            s_here = cd[i]
        else:
            t = max(0.0, min(1.0, (wx*vx + wy*vy) / seg_len2))
            cx, cy = ax + t*vx, ay + t*vy
            d = math.hypot(px - cx, py - cy)
            # segment length in meters within local projection
            seg_len = math.hypot(vx, vy)
            s_here = cd[i] + t * seg_len

        if d < best_d:
            best_d = d
            best_s = s_here

    if best_s is None:
        return 0.5
    frac = best_s / total if total > 0 else 0.5
    # Clamp to [0,1]
    return max(0.0, min(1.0, float(frac)))


# -------------------- Fallback Facilities Loader --------------------
def _load_fallback_facilities() -> Dict[str, List[Dict[str, Any]]]:
    """Load fallback facilities from JSON if available.
    Expected JSON structure:
    {
      "asphalt_plants": [{"name": str, "lat": float, "lon": float}, ...],
      "waste_sites": [{"name": str, "lat": float, "lon": float}, ...],
      "rubber_recycling": [{"name": str, "lat": float, "lon": float}, ...],
      "rubber_production": [{"name": str, "lat": float, "lon": float}, ...]
    }
    Missing file or keys are handled gracefully by returning empty lists.
    """
    empty = {
        "asphalt_plants": [],
        "waste_sites": [],
        "rubber_recycling": [],
        "rubber_production": [],
    }
    try:
        if not os.path.exists(FALLBACK_FILE):
            return empty
        with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for key in empty.keys():
            items = data.get(key) or []
            safe_items: List[Dict[str, Any]] = []
            for it in items:
                try:
                    name = str((it or {}).get("name") or key[:-1])
                    lat = float((it or {}).get("lat"))
                    lon = float((it or {}).get("lon"))
                except Exception:
                    continue
                safe_items.append({"name": name, "lat": lat, "lon": lon})
            out[key] = safe_items
        # Ensure all keys exist
        for k, v in empty.items():
            out.setdefault(k, v)
        return out
    except Exception:
        return empty


def _path_cumdist_m(path: List[Tuple[float, float]]) -> List[float]:
    """Return cumulative distance (meters) along path, starting at 0."""
    cd = [0.0]
    for i in range(1, len(path)):
        d = haversine_m(path[i-1][0], path[i-1][1], path[i][0], path[i][1])
        cd.append(cd[-1] + d)
    return cd


def slice_path_segment(path: List[Tuple[float, float]], length_km: float,
                       anchor: str = "mid", direction: str = "forward") -> List[Tuple[float, float]]:
    """Extract a contiguous path segment by desired length and anchor.
    - length_km: target segment length (km). If <=0 or >= total, returns full path (possibly reversed).
    - anchor: 'start' | 'mid' | 'end'
    - direction: 'forward' | 'reverse'
    Returns a list of (lat, lon).
    """
    if not path or len(path) < 2:
        return path
    try:
        L = max(0.0, float(length_km)) * 1000.0
    except Exception:
        L = 0.0
    if L <= 0.0:
        return list(path if direction == "forward" else reversed(path))

    cd = _path_cumdist_m(path)
    total = cd[-1]
    if total <= 1e-6 or L >= total:
        return list(path if direction == "forward" else reversed(path))

    # choose anchor index
    if anchor == "start":
        idx = 0
    elif anchor == "end":
        idx = len(path) - 1
    else:
        half = total / 2.0
        idx = min(range(len(cd)), key=lambda i: abs(cd[i] - half))

    if direction == "reverse":
        # walk backward from idx
        j = idx
        dist = 0.0
        while j > 0 and dist < L:
            dist += haversine_m(path[j][0], path[j][1], path[j-1][0], path[j-1][1])
            j -= 1
        return path[j:idx+1]
    else:
        # forward
        j = idx
        dist = 0.0
        while j < len(path)-1 and dist < L:
            dist += haversine_m(path[j][0], path[j][1], path[j+1][0], path[j+1][1])
            j += 1
        return path[idx:j+1]


def exp_decay(distance_m: float, tau_m: float) -> float:
    """Exponential decay scoring in [0,1] with scale parameter tau (meters).
    score = exp(-distance/tau).
    """
    if tau_m <= 1e-9:
        return 0.0
    d = max(0.0, float(distance_m))
    try:
        return math.exp(-d / float(tau_m))
    except Exception:
        return 0.0


# -------------------- Overpass Queries --------------------
def overpass_post(query: str, timeout_s: int | None = None, retries: int | None = None) -> Dict[str, Any]:
    """POST a query to Overpass with fallback mirrors and simple retries.
    Timeouts/retries/backoff are configurable via env:
      - OSM_TIMEOUT_S (default 45)
      - OSM_RETRIES (default 2)
      - OSM_BACKOFF (comma-separated seconds, default "1,3,6")
      - OSM_VERBOSE (1/true to enable attempt logs)
    Returns parsed JSON dict or raises the last exception.
    """
    last_exc: Exception | None = None
    to = timeout_s if timeout_s is not None else _env_int("OSM_TIMEOUT_S", 45)
    rts = retries if retries is not None else _env_int("OSM_RETRIES", 2)
    backoff = _env_backoff("OSM_BACKOFF", [1, 3, 6])
    verbose = _env_bool("OSM_VERBOSE", False)
    for attempt in range(rts + 1):
        for url in OVERPASS_URLS:
            try:
                if verbose:
                    print(f"[OSM] attempt {attempt+1}/{rts+1} url={url} timeout={to}s")
                resp = requests.post(url, data={"data": query}, timeout=to)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # requests.RequestException or others
                last_exc = e
                if verbose:
                    print(f"[OSM] error from {url}: {type(e).__name__}: {e}")
                # try next mirror
                continue
        # wait then retry all mirrors again
        if attempt < rts:
            wait_s = backoff[min(attempt, len(backoff)-1)]
            if verbose:
                print(f"[OSM] retrying after {wait_s}s ...")
            time.sleep(wait_s)
    # Exhausted
    if last_exc:
        raise last_exc
    raise RuntimeError("Overpass request failed without exception")
def overpass_query(bbox: Tuple[float, float, float, float], kind: str) -> List[Dict[str, Any]]:
    """Query OSM for facilities of a certain kind within a bbox.
    kind in {"asphalt", "quarry", "rubber", "highway_major", "ready_mix", "bitumen"}
    Returns list of dicts: {id, name, lat, lon, type}
    """
    south, west, north, east = bbox
    if kind == "asphalt":
        # Tags often used: industrial=asphalt; plant=asphalt; product=asphalt
        q = f"""
        [out:json][timeout:25];
        (
          node["industrial"="asphalt"]({south},{west},{north},{east});
          node["plant"="asphalt"]({south},{west},{north},{east});
          node["product"="asphalt"]({south},{west},{north},{east});
          way["industrial"="asphalt"]({south},{west},{north},{east});
          way["plant"="asphalt"]({south},{west},{north},{east});
        );
        out center tags;
        """
    elif kind == "quarry":
        q = f"""
        [out:json][timeout:25];
        (
          node["landuse"="quarry"]({south},{west},{north},{east});
          way["landuse"="quarry"]({south},{west},{north},{east});
        );
        out center tags;
        """
    elif kind == "rubber":
        q = f"""
        [out:json][timeout:25];
        (
          node["amenity"="recycling"]["recycling:rubber"="yes"]({south},{west},{north},{east});
          way["amenity"="recycling"]["recycling:rubber"="yes"]({south},{west},{north},{east});
        );
        out center tags;
        """
    elif kind == "highway_major":
        # Approximate proximity using highway nodes (motorway/trunk). Using nodes keeps geometry light.
        q = f"""
        [out:json][timeout:25];
        (
          node["highway"~"^(motorway|trunk)$"]({south},{west},{north},{east});
        );
        out body;
        """
    elif kind == "ready_mix":
        # Heuristic: industrial=concrete, or plant=concrete
        q = f"""
        [out:json][timeout:25];
        (
          node["industrial"="concrete"]({south},{west},{north},{east});
          node["plant"="concrete"]({south},{west},{north},{east});
          way["industrial"="concrete"]({south},{west},{north},{east});
          way["plant"="concrete"]({south},{west},{north},{east});
        );
        out center tags;
        """
    elif kind == "bitumen":
        # Sparse in OSM: look for storage tanks or industrial sites tagged with bitumen/asphalt product
        q = f"""
        [out:json][timeout:25];
        (
          node["product"~"bitumen|asphalt"]({south},{west},{north},{east});
          way["product"~"bitumen|asphalt"]({south},{west},{north},{east});
          node["man_made"="storage_tank"]["substance"~"bitumen|asphalt"]({south},{west},{north},{east});
          way["man_made"="storage_tank"]["substance"~"bitumen|asphalt"]({south},{west},{north},{east});
        );
        out center tags;
        """
    else:
        return []

    q = q.format(south=south, west=west, north=north, east=east)
    data = overpass_post(q)
    out: List[Dict[str, Any]] = []
    for el in data.get("elements", []):
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center", {})
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("operator") or kind
        out.append({
            "id": el.get("id"),
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
            "type": kind,
        })
    return out


def landuse_near(point: Tuple[float, float], radius_m: float = 200.0) -> Dict[str, Any] | None:
    """Query closest landuse polygon (way/relation) around a point and return its main tag.
    Returns dict {tag: str, id: int} or None if not found.
    """
    lat, lon = point
    q = f"""
    [out:json][timeout:25];
    (
      way(around:{int(radius_m)},{lat},{lon})["landuse"];
      relation(around:{int(radius_m)},{lat},{lon})["landuse"];
    );
    out center tags;
    """
    try:
        data = overpass_post(q, timeout_s=30, retries=1)
    except Exception:
        return None
    best = None
    best_d = 1e12
    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        lu = tags.get("landuse")
        if not lu:
            continue
        if el.get("type") == "node":
            lat2, lon2 = el.get("lat"), el.get("lon")
        else:
            c = el.get("center", {}) or {}
            lat2, lon2 = c.get("lat"), c.get("lon")
        if lat2 is None or lon2 is None:
            continue
        d = haversine_m(lat, lon, float(lat2), float(lon2))
        if d < best_d:
            best_d = d
            best = {"tag": str(lu), "id": el.get("id")}
    return best


# Simple suitability mapping (domain-adjustable)
LANDUSE_SCORES: Dict[str, float] = {
    "industrial": 1.0,
    "brownfield": 0.9,
    "construction": 0.8,
    "greenfield": 0.75,
    "quarry": 0.7,
    "landfill": 0.7,
    "meadow": 0.6,
    "grass": 0.6,
    "farmland": 0.45,
    "commercial": 0.35,
    "retail": 0.25,
    "forest": 0.20,
    "residential": 0.0,
    "military": 0.0,
    "cemetery": 0.0,
    "reservoir": 0.0,
}


def landuse_score(point: Tuple[float, float]) -> Tuple[float, str | None]:
    """Return (score[0..1], label) for landuse near the point using OSM.
    If no landuse found, return (0.5, None) as neutral.
    """
    # Cache by rounded coordinate to minimize Overpass calls
    global _LANDUSE_CACHE
    try:
        _ = _LANDUSE_CACHE
    except NameError:
        _LANDUSE_CACHE = {}
    key = f"{point[0]:.5f},{point[1]:.5f}"
    if key in _LANDUSE_CACHE:
        return _LANDUSE_CACHE[key]
    info = landuse_near(point, 250.0)
    if not info or not info.get("tag"):
        res = (0.5, None)
        _LANDUSE_CACHE[key] = res
        return res
    tag = str(info["tag"]).lower()
    score = LANDUSE_SCORES.get(tag)
    if score is None:
        # Unknown landuse: mildly conservative
        score = 0.5
    res = (float(score), tag)
    _LANDUSE_CACHE[key] = res
    return res


def buildings_count_within(point: Tuple[float, float], radius_m: float = 120.0) -> int:
    """Heuristic for land availability: count buildings within radius.
    Lower count suggests open land. Uses Overpass around a small circle.
    """
    lat, lon = point
    q = f"""
    [out:json][timeout:20];
    (
      way(around:{int(radius_m)},{lat},{lon})["building"]; 
      relation(around:{int(radius_m)},{lat},{lon})["building"]; 
    );
    out ids;
    """
    try:
        data = overpass_post(q, timeout_s=30, retries=1)
        return len(data.get("elements", []))
    except Exception:
        # On failure, assume dense (not land-OK) by returning a positive count
        # but keep light to avoid zeroing all scores.
        return 3


# -------------------- Scoring Engine --------------------
def score_candidate(point: Tuple[float, float], path: List[Tuple[float, float]],
                    quarries: List[Dict[str, Any]], rubbers: List[Dict[str, Any]],
                    highways: List[Dict[str, Any]] | None = None,
                    ready_mix: List[Dict[str, Any]] | None = None,
                    bitumen_sources: List[Dict[str, Any]] | None = None,
                    weights: Dict[str, float] = DEFAULT_WEIGHTS) -> Dict[str, Any]:
    # Components
    d_road = min_distance_to_path_m(point, path)
    # Exponential decay around the path (scale ~1500 m)
    near_road_score = exp_decay(d_road, 1500.0)

    mid = path_midpoint(path)
    d_mid = haversine_m(point[0], point[1], mid[0], mid[1])
    # Exponential decay with a larger scale (~25 km)
    mid_score = exp_decay(d_mid, 25000.0)

    def nearest_distance_m(cands: List[Dict[str, Any]]) -> float:
        if not cands:
            return 1e9
        return min(haversine_m(point[0], point[1], c["lat"], c["lon"]) for c in cands)

    d_quarry = nearest_distance_m(quarries)
    quarry_score = exp_decay(d_quarry, 50000.0)

    d_rubber = nearest_distance_m(rubbers)
    rubber_score = exp_decay(d_rubber, 50000.0)

    # Optional layers
    d_highway = nearest_distance_m(highways or [])
    highway_score = exp_decay(d_highway, 8000.0)  # 8 km scale for major highways

    d_ready = nearest_distance_m(ready_mix or [])
    ready_mix_score = exp_decay(d_ready, 50000.0)

    d_bit = nearest_distance_m(bitumen_sources or [])
    bitumen_score = exp_decay(d_bit, 80000.0)

    # Land context: OSM landuse + soft building density penalty
    lu_score, lu_label = landuse_score(point)
    bcnt = buildings_count_within(point, 120.0)
    # Soft penalty: more buildings reduce score but don't zero it out completely
    if bcnt <= 2:
        b_pen = 1.0
    elif bcnt <= 5:
        b_pen = 0.7
    else:
        b_pen = 0.4

    base_score = (
        weights.get("road_proximity", 5.0) * near_road_score +
        weights.get("midpoint_preference", 4.0) * mid_score +
        weights.get("quarry_proximity", 2.0) * quarry_score +
        weights.get("rubber_proximity", 1.0) * rubber_score +
        weights.get("landuse_preference", 3.0) * lu_score +
        weights.get("highway_proximity", 2.5) * highway_score +
        # ready-mix score is computed for reporting but intentionally excluded from weighted total
        weights.get("bitumen_source_proximity", 1.0) * bitumen_score
    )
    # If landuse is strongly unsuitable (e.g., residential), clamp to zero
    if lu_score <= 0.05:
        total = 0.0
    else:
        total = float(base_score) * b_pen
        # Heavy penalty for sites near the first/last 10% of path length
        try:
            frac = path_fraction_at_point(point, path)
        except Exception:
            frac = 0.5
        if frac <= 0.10 or frac >= 0.90:
            total *= 0.2  # strongly discourage edge sites

    # Normalized total in [0,1] relative to sum of weights
    wsum = sum(max(0.0, float(v)) for v in weights.values()) or 1.0
    total_norm = max(0.0, min(1.0, total / wsum))

    return {
        "point": {"lat": point[0], "lon": point[1]},
        "scores": {
            "near_road": near_road_score,
            "midpoint": mid_score,
            "quarry": quarry_score,
            "rubber": rubber_score,
            "highway": highway_score,
            "ready_mix": ready_mix_score,
            "bitumen": bitumen_score,
            "landuse_score": lu_score,
            "landuse_label": lu_label,
            "buildings_count": bcnt,
        },
        "total_score": total,
        "total_score_norm": total_norm,
    }


def analyze_path(path: List[Tuple[float, float]], mode: str = "new", top_k: int = 5,
                 weights: Dict[str, float] = DEFAULT_WEIGHTS) -> Dict[str, Any]:
    """Main entry: given a path (list of (lat, lon)), return analysis dict with:
    - existing: asphalt plants within radius with scores
    - proposed: suggested new candidate(s) with scores
    - map_path: generated folium map path if folium available
    """
    if not path or len(path) < 2:
        raise ValueError("Path must contain at least two points (lat, lon)")

    south, west, north, east = path_bbox(path)
    # Expand bbox by ~50km
    lat_pad = 0.5
    lon_pad = 0.5
    bbox = (south - lat_pad, west - lon_pad, north + lat_pad, east + lon_pad)

    # Fetch facilities (OSM)
    asphalt = overpass_query(bbox, "asphalt")
    quarries = overpass_query(bbox, "quarry")
    rubbers = overpass_query(bbox, "rubber")
    highways = overpass_query(bbox, "highway_major")
    ready_mix = overpass_query(bbox, "ready_mix")
    bitumen_sources = overpass_query(bbox, "bitumen")

    # Load fallback facilities (local JSON) and keep only those within 200 km of the path.
    # Use them ONLY if corresponding OSM results are absent.
    fb = _load_fallback_facilities()
    def _annotate_and_filter(items: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for it in items or []:
            lat = it.get("lat"); lon = it.get("lon")
            if lat is None or lon is None:
                continue
            d = min_distance_to_path_m((float(lat), float(lon)), path)
            if d <= SEARCH_RADIUS_M:
                it2 = {
                    "name": it.get("name") or kind,
                    "lat": float(lat),
                    "lon": float(lon),
                    "type": kind,
                    "distance_to_path_m": float(d),
                }
                out.append(it2)
        # sort nearest first
        out.sort(key=lambda x: x.get("distance_to_path_m", 1e12))
        return out

    # Annotate all fallback categories first
    _fb_asphalt_all = _annotate_and_filter(fb.get("asphalt_plants", []), "fallback_asphalt")
    _fb_waste_all = _annotate_and_filter(fb.get("waste_sites", []), "fallback_waste")
    _fb_rubber_rec_all = _annotate_and_filter(fb.get("rubber_recycling", []), "fallback_rubber_recycling")
    _fb_rubber_prod_all = _annotate_and_filter(fb.get("rubber_production", []), "fallback_rubber_production")

    # Gate by presence of OSM results
    has_osm_asphalt = len(asphalt) > 0
    has_osm_rubber = len(rubbers) > 0

    # Use asphalt fallback only if no OSM asphalt found
    fallback_asphalt = ([] if has_osm_asphalt else _fb_asphalt_all)
    # Use rubber recycling fallback only if no OSM rubber found
    fallback_rubber_recycling = ([] if has_osm_rubber else _fb_rubber_rec_all)
    # For waste and rubber production (no direct OSM counterparts here),
    # use them only if there are no asphalt nor rubber OSM results at all
    if not (has_osm_asphalt or has_osm_rubber):
        fallback_waste = _fb_waste_all
        fallback_rubber_production = _fb_rubber_prod_all
    else:
        fallback_waste = []
        fallback_rubber_production = []

    # Score existing asphalt plants
    existing_scored: List[Dict[str, Any]] = []
    for a in asphalt:
        sc = score_candidate((a["lat"], a["lon"]), path, quarries, rubbers, highways, ready_mix, bitumen_sources, weights)
        a2 = dict(a)
        a2["score"] = sc
        existing_scored.append(a2)
    existing_scored.sort(key=lambda x: x.get("score", {}).get("total_score", 0.0), reverse=True)

    # Propose new sites: one per full 200 km segment, placed at the 100 km midpoint
    proposed_points = []
    used = set()
    cd = _path_cumdist_m(path)
    total = cd[-1] if cd else 0.0
    SEG_M = 200_000.0  # 200 km in meters
    MID_M = 100_000.0  # 100 km in meters
    if total >= SEG_M:
        num_full = int(total // SEG_M)
        for k in range(num_full):
            target = k * SEG_M + MID_M
            pt = point_at_distance_m(path, target)
            key = (round(pt[0], 5), round(pt[1], 5))
            if key in used:
                continue
            used.add(key)
            proposed_points.append(pt)

    proposed_scored: List[Dict[str, Any]] = []
    for p in proposed_points:
        sc = score_candidate(p, path, quarries, rubbers, highways, ready_mix, bitumen_sources, weights)
        proposed_scored.append({
            "name": "Proposed Site",
            "lat": p[0],
            "lon": p[1],
            "type": "proposed",
            "score": sc,
        })
    proposed_scored.sort(key=lambda x: x.get("score", {}).get("total_score", 0.0), reverse=True)

    # Keep top_k for existing, but return ALL proposed (one per full 200 km segment)
    existing_top = existing_scored[:top_k]
    proposed_top = proposed_scored

    # Build map if folium available
    map_path = None
    if folium is not None:
        start = path[0]
        m = folium.Map(location=[start[0], start[1]], zoom_start=9, control_scale=True)
        folium.PolyLine(path, color="#1f77b4", weight=4, opacity=0.9, tooltip="Path").add_to(m)
        # Existing plants
        for a in existing_top:
            sc = a.get("score", {})
            popup = folium.Popup(html=f"""
                <b>{a.get('name','Asphalt Plant')}</b><br/>
                Score: {sc.get('total_score',0):.2f}<br/>
                NearRoad: {sc.get('scores',{}).get('near_road',0):.2f}<br/>
                Quarry: {sc.get('scores',{}).get('quarry',0):.2f}<br/>
                Rubber: {sc.get('scores',{}).get('rubber',0):.2f}<br/>
                Highway: {sc.get('scores',{}).get('highway',0):.2f}<br/>
                ReadyMix: {sc.get('scores',{}).get('ready_mix',0):.2f}<br/>
                Bitumen: {sc.get('scores',{}).get('bitumen',0):.2f}<br/>
                Landuse: {sc.get('scores',{}).get('landuse_label','-')} ({sc.get('scores',{}).get('landuse_score',0):.2f})<br/>
                Buildings(120m): {sc.get('scores',{}).get('buildings_count',0)}
            """, max_width=250)
            folium.Marker([a["lat"], a["lon"]],
                          icon=folium.Icon(color="green", icon="industry", prefix="fa"),
                          tooltip=a.get("name"), popup=popup).add_to(m)
        # Proposed
        for p in proposed_top:
            sc = p.get("score", {})
            popup = folium.Popup(html=f"""
                <b>{p.get('name','Proposed')}</b><br/>
                Score: {sc.get('total_score',0):.2f}<br/>
                Highway: {sc.get('scores',{}).get('highway',0):.2f}<br/>
                ReadyMix: {sc.get('scores',{}).get('ready_mix',0):.2f}<br/>
                Bitumen: {sc.get('scores',{}).get('bitumen',0):.2f}<br/>
                Landuse: {sc.get('scores',{}).get('landuse_label','-')} ({sc.get('scores',{}).get('landuse_score',0):.2f})<br/>
                Buildings(120m): {sc.get('scores',{}).get('buildings_count',0)}
            """, max_width=250)
            folium.Marker([p["lat"], p["lon"]],
                          icon=folium.Icon(color="red", icon="plus", prefix="fa"),
                          tooltip=p.get("name"), popup=popup).add_to(m)
        # Fallback facilities layers (distinct markers)
        # Asphalt (triangle)
        for it in fallback_asphalt:
            folium.features.RegularPolygonMarker(
                location=[it["lat"], it["lon"]],
                number_of_sides=3,
                radius=10,
                color="#f39c12",
                fill=True,
                fill_color="#f39c12",
                tooltip=f"{it.get('name','Asphalt (FB)')} (≈{it.get('distance_to_path_m',0)/1000:.1f} km)",
                popup=folium.Popup(html=f"""
                    <b>{it.get('name','Asphalt (FB)')}</b><br/>
                    نوع: مرافق احتياطية - أسفلت<br/>
                    المسافة للطريق: {it.get('distance_to_path_m',0)/1000:.2f} كم
                """, max_width=240)
            ).add_to(m)
        # Waste (square)
        for it in fallback_waste:
            folium.features.RegularPolygonMarker(
                location=[it["lat"], it["lon"]],
                number_of_sides=4,
                radius=8,
                color="#8e44ad",
                fill=True,
                fill_color="#8e44ad",
                tooltip=f"{it.get('name','Waste (FB)')} (≈{it.get('distance_to_path_m',0)/1000:.1f} km)",
                popup=folium.Popup(html=f"""
                    <b>{it.get('name','Waste (FB)')}</b><br/>
                    نوع: مرافق احتياطية - مخلفات/نفايات<br/>
                    المسافة للطريق: {it.get('distance_to_path_m',0)/1000:.2f} كم
                """, max_width=240)
            ).add_to(m)
        # Rubber recycling (star icon)
        for it in fallback_rubber_recycling:
            folium.Marker(
                [it["lat"], it["lon"]],
                icon=folium.Icon(color="blue", icon="star", prefix="fa"),
                tooltip=f"{it.get('name','Rubber Recycle (FB)')} (≈{it.get('distance_to_path_m',0)/1000:.1f} km)",
                popup=folium.Popup(html=f"""
                    <b>{it.get('name','Rubber Recycle (FB)')}</b><br/>
                    نوع: مرافق احتياطية - تدوير المطاط<br/>
                    المسافة للطريق: {it.get('distance_to_path_m',0)/1000:.2f} كم
                """, max_width=240)
            ).add_to(m)
        # Rubber production (circle)
        for it in fallback_rubber_production:
            folium.CircleMarker(
                location=[it["lat"], it["lon"]],
                radius=6,
                color="#2ecc71",
                fill=True,
                fill_opacity=0.9,
                fill_color="#2ecc71",
                tooltip=f"{it.get('name','Rubber Production (FB)')} (≈{it.get('distance_to_path_m',0)/1000:.1f} km)",
                popup=folium.Popup(html=f"""
                    <b>{it.get('name','Rubber Production (FB)')}</b><br/>
                    نوع: مرافق احتياطية - إنتاج المطاط<br/>
                    المسافة للطريق: {it.get('distance_to_path_m',0)/1000:.2f} كم
                """, max_width=240)
            ).add_to(m)
        # Legend (Map Key)
        # Add a fixed small box explaining markers and colors for end users
        try:
            legend_html = """
            <div style="
                position: fixed;
                bottom: 56px;
                left: 10px;
                z-index: 999999;
                background: white;
                padding: 10px 12px;
                border: 2px solid rgba(0,0,0,0.2);
                border-radius: 8px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.2);
                font-size: 13px;
                line-height: 1.2;
                direction: rtl;
            ">
              <div style="font-weight: 700; margin-bottom: 6px;">مفتاح الخريطة</div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <span style="display:inline-block; width:18px; height:4px; background:#1f77b4;"></span>
                <span>الخط الأزرق → المسار</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <i class="fa fa-map-marker" style="color: green; font-size:16px;"></i>
                <span>Pin أخضر → محطة أسفلت موجودة</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <i class="fa fa-map-marker" style="color: red; font-size:16px;"></i>
                <span>Pin أحمر → موقع مقترح</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <svg width="16" height="16" viewBox="0 0 16 16">
                  <polygon points="8,2 14,14 2,14" fill="#f39c12" stroke="#f39c12" />
                </svg>
                <span>مثلث برتقالي → محطة أسفلت احتياطية</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <svg width="16" height="16" viewBox="0 0 16 16">
                  <rect x="3" y="3" width="10" height="10" fill="#8e44ad" stroke="#8e44ad" />
                </svg>
                <span>مربع بنفسجي → موقع نفايات</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <i class="fa fa-star" style="color: #2980b9; font-size:16px;"></i>
                <span>نجمة زرقاء → مصنع تدوير مطاط</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px; margin:4px 0;">
                <svg width="16" height="16" viewBox="0 0 16 16">
                  <circle cx="8" cy="8" r="5" fill="#2ecc71" stroke="#27ae60" />
                </svg>
                <span>دائرة خضراء → مصنع إنتاج مطاط</span>
              </div>
            </div>
            """
            m.get_root().html.add_child(folium.Element(legend_html))
        except Exception:
            # Legend is non-critical; ignore failures to keep map generation robust
            pass
        # Save
        runs_dir = os.path.join(os.path.dirname(__file__), "runs")
        os.makedirs(runs_dir, exist_ok=True)
        map_path = os.path.join(runs_dir, f"planner_map_{int(time.time())}.html")
        try:
            m.save(map_path)
        except Exception:
            map_path = None

    return {
        "existing": existing_top,
        "proposed": proposed_top,
        "quarries": quarries,
        "rubbers": rubbers,
        "highways": highways,
        "ready_mix": ready_mix,
        "bitumen_sources": bitumen_sources,
        "fallback_asphalt": fallback_asphalt,
        "fallback_waste": fallback_waste,
        "fallback_rubber_recycling": fallback_rubber_recycling,
        "fallback_rubber_production": fallback_rubber_production,
        "map_path": map_path,
    }


def load_geojson_path(path_file: str) -> List[Tuple[float, float]]:
    """Load a LineString/MultiLineString GeoJSON and return list of (lat, lon)."""
    with open(path_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    def coords_to_list(coords):
        out = []
        for c in coords:
            if isinstance(c[0], list):
                out.extend(coords_to_list(c))
            else:
                # geojson lon,lat
                out.append((float(c[1]), float(c[0])))
        return out
    g = data.get("geometry") or data.get("features", [{}])[0].get("geometry")
    if not g:
        raise ValueError("Invalid GeoJSON: no geometry found")
    if g.get("type") == "LineString":
        coords = g.get("coordinates", [])
        return coords_to_list(coords)
    if g.get("type") == "MultiLineString":
        coords = g.get("coordinates", [])
        return coords_to_list(coords)
    raise ValueError("Unsupported GeoJSON geometry type; expected LineString/MultiLineString")
