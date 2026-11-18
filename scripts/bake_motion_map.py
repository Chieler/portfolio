"""Bake the selected gallery routes with Motion's cached OSM street graphs.

Run with Motion's backend Python dependencies installed:
    python scripts/bake_motion_map.py

Street data © OpenStreetMap contributors, ODbL (openstreetmap.org/copyright).
"""
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from shapely import get_parts, line_merge, polygonize, union_all, wkt
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import transform

PORTFOLIO = Path(__file__).resolve().parents[1]
MOTION = PORTFOLIO.parent / "motion"
PUBLIC = MOTION / "app-frontend/public"
BACKEND = MOTION / "backend"
SIZE = 800
EARTH_RADIUS = 6_371_008.8
MAJOR = {"primary", "secondary", "tertiary", "trunk", "motorway"}
LOCAL = {"residential", "living_street", "unclassified", "road", "pedestrian"}
DETAIL = {"footway", "cycleway", "path", "steps", "track"}
SELECTIONS = {
    "capybara": ("capybara-09", "sanfrancisco"),
    "horse": ("horse-06", "sanfrancisco"),
    "elephant": ("elephant-08", "manhattan"),
}


def selected_routes():
    gallery = (PORTFOLIO / "motion-examples.html").read_text()
    payload = re.search(r'id="route-examples">(.*?)</script>', gallery, re.S)
    if payload is None:
        raise ValueError("Route data is missing from motion-examples.html.")
    groups = json.loads(payload[1])
    for animal, (route_id, city) in SELECTIONS.items():
        group = groups[animal]
        selected = next((route for route in group["options"] if route["id"] == route_id), None)
        if selected is None:
            raise ValueError(f"{route_id} is missing from motion-examples.html.")
        yield animal, city, {"id": route_id, "location": group["city"], "route": selected["gps"]}


def streets(city):
    graph = ET.parse(BACKEND / "graph_cache" / f"{city}.graphml").getroot()
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    keys = {key.get("id"): key.get("attr.name") for key in graph.findall("g:key", ns)}

    def tags(element):
        return {keys[tag.get("key")]: tag.text for tag in element.findall("g:data", ns)}

    nodes = {}
    for node in graph.findall("g:graph/g:node", ns):
        data = tags(node)
        nodes[node.get("id")] = (float(data["x"]), float(data["y"]))

    seen = set()
    for edge in graph.findall("g:graph/g:edge", ns):
        data = tags(edge)
        highway = data.get("highway", "")
        classes = set(highway.strip("[]").replace("'", "").replace(" ", "").split(","))
        if classes & MAJOR:
            layer = "arteries"
        elif classes & LOCAL:
            layer = "streets"
        elif classes & DETAIL:
            layer = "paths"
        else:
            continue
        geometry = (
            wkt.loads(data["geometry"]) if "geometry" in data
            else LineString([nodes[edge.get("source")], nodes[edge.get("target")]])
        )
        fingerprint = geometry.normalize().wkb
        if fingerprint not in seen:
            seen.add(fingerprint)
            yield layer, geometry


def line_path(coords, precision=0):
    return "M" + " ".join(f"{x:.{precision}f} {y:.{precision}f}" for x, y in coords)


def bake(demo, network):
    coords = demo["route"]
    lat = sum(lat for lat, _ in coords) / len(coords)
    lon = sum(lon for _, lon in coords) / len(coords)
    meters = math.pi / 180 * EARTH_RADIUS
    longitude_scale = math.cos(math.radians(lat)) * meters

    def project(x, y):
        return (x - lon) * longitude_scale, (lat - y) * meters

    route = LineString([project(x, y) for y, x in coords])
    x0, y0, x1, y1 = route.bounds
    center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
    scale = SIZE / (max(x1 - x0, y1 - y0) * 1.25)

    def to_map(x, y):
        mx, my = project(x, y)
        return (mx - center_x) * scale + SIZE / 2, (my - center_y) * scale + SIZE / 2

    layers = {"paths": [], "streets": [], "arteries": []}
    viewport = box(0, 0, SIZE, SIZE)
    for layer, geometry in network:
        line = transform(to_map, geometry)
        if not line.intersects(viewport):
            continue
        for part in get_parts(line.intersection(viewport)):
            if part.geom_type == "LineString" and part.length > 0.5:
                layers[layer].append(part.simplify(0.18))

    # Polygonize the street centerlines so the visible blocks inherit the real
    # street angles. Inset their edges to leave a clear street-width gutter.
    block_paths = []
    centerlines = union_all(layers["streets"] + layers["arteries"], grid_size=0.05)
    for block in get_parts(polygonize(get_parts(centerlines))):
        if block.area < 30 or block.area > 15000:
            continue
        for inset in get_parts(block.buffer(-2.7, join_style="mitre")):
            if inset.area > 15:
                rings = [inset.exterior, *inset.interiors]
                block_paths.extend(line_path(ring.coords[:-1]) + "Z" for ring in rings)

    # Sub-block paths add useful context in parks and plazas. Drop short
    # fragments after joining paths so crossings don't compete with the grid.
    trails = get_parts(line_merge(MultiLineString(layers["paths"])))
    layers["paths"] = [trail.simplify(0.5) for trail in trails if trail.length >= 8]

    return {
        "id": demo["id"],
        "city": demo["location"],
        "km": f"{route.length / 1000:.1f}",
        "route": line_path((to_map(x, y) for y, x in coords), precision=1),
        "blocks": "".join(block_paths),
        **{layer: "".join(line_path(part.coords) for part in lines)
           for layer, lines in layers.items()},
    }


def main():
    networks = {city: list(streets(city)) for city in dict.fromkeys(city for _, city in SELECTIONS.values())}
    data = {animal: bake(demo, networks[city]) for animal, city, demo in selected_routes()}
    (PORTFOLIO / "assets/motion-map-data.js").write_text(
        "// Generated by scripts/bake_motion_map.py. Street data © OpenStreetMap contributors (ODbL).\n"
        + "window.MOTION_MAPS = " + json.dumps(data, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
