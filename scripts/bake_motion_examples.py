"""Generate the route gallery using Motion's offline city graphs.

Run from the portfolio checkout with Motion's backend Python dependencies:
    python scripts/bake_motion_examples.py
"""
from concurrent.futures import ProcessPoolExecutor
import json
import math
import re
import sys

from shapely import get_parts, line_merge
from shapely.geometry import MultiLineString

from bake_motion_map import BACKEND, PORTFOLIO, PUBLIC

ANIMALS = {
    "capybara": ("San Francisco", "sanfrancisco", 37.7749, -122.4194),
    "horse": ("San Francisco", "sanfrancisco", 37.7749, -122.4194),
    "elephant": ("Manhattan, NY", "manhattan", 40.7527, -73.9943),
}


def gallery_geometry(route, target, streets):
    points = [*route, *target]
    west, east = min(x for x, _ in points), max(x for x, _ in points)
    south, north = min(y for _, y in points), max(y for _, y in points)
    span = max(east - west, north - south) * 1.18
    cx, cy = (west + east) / 2, (north + south) / 2

    def project(x, y):
        return round(150 + (x - cx) * 300 / span, 1), round(150 - (y - cy) * 300 / span, 1)

    def path(line):
        return "M" + " ".join(f"{x:g} {y:g}" for x, y in (project(*p) for p in line))

    # Keep the longer street segments as context behind the route. The
    # gallery doesn't need the router's full graph for every alternative.
    visible = []
    half = span / 2
    for a, b in streets:
        if math.dist(a, b) < span * 0.002:
            continue
        if (min(a[0], b[0]) <= cx + half and max(a[0], b[0]) >= cx - half
                and min(a[1], b[1]) <= cy + half and max(a[1], b[1]) >= cy - half):
            visible.append((a, b))
    merged = get_parts(line_merge(MultiLineString(visible)))
    reference = sorted(merged, key=lambda line: line.length, reverse=True)[:1200]
    return {
        "trace": path(route),
        "guide": path([*target, target[0]]),
        "streets": "".join(path(line.simplify(span * 0.0008).coords) for line in reference),
    }


def search(job):
    animal, radius, seed, strict = job
    _, slug, lat, lng = ANIMALS[animal]
    sys.path.insert(0, str(BACKEND))
    import spatial_engine as engine

    config = engine.make_config(
        lat, lng, radius,
        graphml_path=str(BACKEND / "graph_cache" / f"{slug}.graphml"),
        include_parks=False, seed=seed, n_random=280, n_refine=100, n_route_eval=12,
    )
    grid = engine._gen().build_grid(config)
    svg = (PUBLIC / f"{animal}-svgrepo-com.svg").read_bytes()
    warp = {"aspect_max": 1.06, "shear_max": 0.035, "bend_template": False} if strict else {}
    options, _ = engine.route_candidates_from_svg(
        svg, grid, config, inner_features=False, n_placements=4,
        extra_modes=() if strict else ("hybrid",), detail_variants=(), warp=warp,
    )
    entries = []
    for option in options:
        if option["label"] == "Direct":
            continue
        route, target = option["route"], option["placed"]
        entries.append({
            "mode": "Shape-preserving" if strict else option["label"],
            "km": round(option["metrics"]["distance_m"] / 1000, 1),
            "gps": [[round(y, 6), round(x, 6)] for y, x in
                    engine.normalized_to_latlng(route, grid, lat, lng)],
            **gallery_geometry(route, target, grid.edge_list),
        })
    print(f"{animal}: {len(entries)} routes ({'shape-preserving' if strict else 'standard'})", flush=True)
    return animal, entries


def main():
    jobs = [(animal, radius, seed, strict) for animal in ANIMALS
            for radius, seed, strict in ((1600, 42, False), (2050, 137, True))]
    jobs.append(("horse", 2250, 593, True))
    groups = {animal: {"city": city, "options": []}
              for animal, (city, *_rest) in ANIMALS.items()}
    with ProcessPoolExecutor(max_workers=2) as pool:
        for animal, entries in pool.map(search, jobs):
            for entry in entries:
                group = groups[animal]["options"]
                if any(item["trace"] == entry["trace"] for item in group):
                    continue
                entry["id"] = f"{animal}-{len(group) + 1:02}"
                group.append(entry)
    if any(len(group["options"]) < 4 for group in groups.values()):
        raise RuntimeError("Each animal needs at least four route candidates.")
    file = PORTFOLIO / "motion-examples.html"
    html = file.read_text()
    payload = json.dumps(groups, separators=(",", ":"))
    match = r'(<script type="application/json" id="route-examples">).*?(</script>)'
    html, count = re.subn(match, lambda m: m[1] + payload + m[2], html, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Gallery data placeholder is missing.")
    file.write_text(html)


if __name__ == "__main__":
    main()
