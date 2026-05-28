#!/usr/bin/env python3
"""gen_maps.py - regenerate the four region map PNGs for wwigr.org.

Plots the living Top 100 as numbered bubbles (the number is the Top 100
rank) on a tiled CartoDB basemap. A faint connector ties each bubble to
the researcher's true institution location when declutter moved it.

Usage:  python gen_maps.py          generate all four maps
        python gen_maps.py 0|1|2|3  generate one map (world/NA/EU/Asia)

Output: _site/img/10_top100_overview.png and 11/12/13 regional PNGs.
"""
import csv, glob, math, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import contextily as cx
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"
UP = ROOT.parent
DOT = "#b2243a"
MANUAL_GEO = {"university of waikato": (-37.788, 175.317)}
R_EARTH = 6378137.0
cx.set_cache_dir("/tmp/cxcache")


def norm(s):
    return " ".join((s or "").strip().lower().split())


def merc(lat, lon):
    lat = max(min(lat, 85.0), -85.0)
    return (math.radians(lon) * R_EARTH,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH)


def load_living():
    rows = []
    for pat in ("out/gb_top100_*.csv", "out/gb_next100_*.csv"):
        m = sorted(glob.glob(str(UP / pat)))
        with open(m[-1], encoding="utf-8") as f:
            rows += list(csv.DictReader(f))
    enr = {}
    ew = sorted(glob.glob(str(UP / "out-wd/gb_wikidata_enrich_*.csv")))
    if ew:
        with open(ew[-1], encoding="utf-8") as f:
            for r in csv.DictReader(f):
                dd = (r.get("death_date") or "").strip()
                enr[r["name"]] = "" if dd.upper() == "NA" else dd
    ov = {}
    p = ROOT / "data_overrides.csv"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for o in csv.DictReader(f):
                ov[o["name"]] = {k: o[k].strip() for k in
                                 ("institution", "country", "death_date")
                                 if (o.get(k) or "").strip()}
    for r in rows:
        o = ov.get(r["name"], {})
        if "institution" in o:
            r["institution"] = o["institution"]
        if "country" in o:
            r["country"] = o["country"]
        r["_dead"] = bool(o.get("death_date") or enr.get(r["name"], ""))
    rows.sort(key=lambda r: int(r["merged_rank"]))
    return [r for r in rows if not r["_dead"]][:100]


def load_geo():
    geo = {}
    with open(UP / "out/cache/gb_affiliations_geocoded.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                geo[norm(r["institution"])] = (float(r["lat"]), float(r["lon"]))
            except (ValueError, TypeError):
                pass
    return geo


def declutter(pos, min_sep, iters=110):
    n = len(pos)
    for _ in range(iters):
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[j][0] - pos[i][0]
                dy = pos[j][1] - pos[i][1]
                d = math.hypot(dx, dy)
                if d > min_sep:
                    continue
                if d < 1e-6:
                    dx, dy, d = min_sep, 0.0, min_sep
                push = (min_sep - d) / 2.0
                ux, uy = dx / d, dy / d
                pos[i][0] -= ux * push
                pos[i][1] -= uy * push
                pos[j][0] += ux * push
                pos[j][1] += uy * push


def draw(pts, extent, title, outpath, figsize, zoom):
    lon0, lon1, lat0, lat1 = extent
    x0, y0 = merc(lat0, lon0)
    x1, y1 = merc(lat1, lon1)
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)

    inside = []
    for rank, lat, lon in pts:
        x, y = merc(lat, lon)
        if x0 <= x <= x1 and y0 <= y <= y1:
            inside.append((rank, x, y))

    cx.add_basemap(ax, source=cx.providers.CartoDB.Voyager,
                   zoom=zoom, crs="EPSG:3857", attribution_size=6)

    true_xy = [(x, y) for _, x, y in inside]
    label_xy = [[x, y] for _, x, y in inside]
    declutter(label_xy, min_sep=(x1 - x0) * 0.040)

    for (tx, ty), (lx, ly) in zip(true_xy, label_xy):
        if math.hypot(lx - tx, ly - ty) > (x1 - x0) * 0.012:
            ax.plot([tx, lx], [ty, ly], color="#6b6b6b", lw=0.5, zorder=4)
            ax.scatter([tx], [ty], s=9, c="#6b6b6b", zorder=4)
    ax.scatter([p[0] for p in label_xy], [p[1] for p in label_xy],
               s=150, c=DOT, edgecolors="white", linewidths=1.0, zorder=6)
    for (rank, _, _), (lx, ly) in zip(inside, label_xy):
        t = ax.text(lx, ly, str(rank), fontsize=6.6 if rank < 100 else 5.6,
                    fontweight="bold", ha="center", va="center",
                    color="white", zorder=7)
        t.set_path_effects([pe.withStroke(linewidth=0.6, foreground="#7a0f1e")])

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    ax.set_title(title, fontsize=15, color="#003366", fontweight="bold", pad=8)
    fig.savefig(outpath, dpi=145, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {outpath.name}  ({len(inside)} numbered dots)")


NA_COUNTRIES = {"US", "CA", "MX"}
EU_COUNTRIES = {
    "AD","AL","AT","BA","BE","BG","BY","CH","CY","CZ","DE","DK","EE","ES",
    "FI","FO","FR","GB","GR","HR","HU","IE","IS","IT","LI","LT","LU","LV",
    "MC","MD","ME","MK","MT","NL","NO","PL","PT","RO","RS","RU","SE","SI",
    "SK","SM","UA","VA","XK",
}
AS_COUNTRIES = {
    "AE","AF","AM","AU","AZ","BD","BH","BN","BT","CN","GE","HK","ID","IL",
    "IN","IQ","IR","JO","JP","KG","KH","KP","KR","KW","KZ","LA","LB","LK",
    "MM","MN","MO","MV","MY","NP","NZ","OM","PG","PH","PK","PS","QA","SA",
    "SG","SY","TH","TJ","TL","TM","TR","TW","UZ","VN","YE","FJ",
}
# 5th tuple slot is the country filter set (None = no filter / world view).
MAPS = [
    ((-165, 185, -50, 74), "Top 100 Goldbach researchers worldwide",
     "10_top100_overview.png", (13, 6.6), 2, None),
    ((-126, -62, 25, 52), "Top 100 researchers in North America",
     "11_top100_north_america.png", (11, 5.6), 4, NA_COUNTRIES),
    ((-11, 38, 31, 63), "Top 100 researchers in Europe",
     "12_top100_europe.png", (10, 7.0), 4, EU_COUNTRIES),
    ((25, 182, -48, 47),
     "Top 100 researchers in Asia, the Middle East, and the Pacific",
     "13_top100_asia.png", (13, 6.6), 3, AS_COUNTRIES),
    ((-165, 185, -50, 74), "Top 100 researchers in other regions",
     "14_top100_other.png", (13, 6.6), 2, "OTHER"),
]


def main():
    living = load_living()
    geo = load_geo()
    pts, missed = [], []
    for i, r in enumerate(living, 1):
        key = norm(r["institution"])
        ll = geo.get(key) or MANUAL_GEO.get(key)
        if ll:
            pts.append((i, ll[0], ll[1], (r.get("country") or "").strip()))
        else:
            missed.append(f"#{i} {r['name']}")
    print(f"living {len(living)}; geocoded {len(pts)}; missing {missed}")
    (SITE / "img").mkdir(parents=True, exist_ok=True)
    which = ([int(sys.argv[1])] if len(sys.argv) > 1
             else range(len(MAPS)))
    named = NA_COUNTRIES | EU_COUNTRIES | AS_COUNTRIES
    for idx in which:
        extent, title, fn, figsize, zoom, cset = MAPS[idx]
        if cset is None:
            sub = [(r, lat, lon) for r, lat, lon, c in pts]
        elif cset == "OTHER":
            sub = [(r, lat, lon) for r, lat, lon, c in pts if c not in named]
        else:
            sub = [(r, lat, lon) for r, lat, lon, c in pts if c in cset]
        draw(sub, extent, title, SITE / "img" / fn, figsize, zoom)
    print("done")


if __name__ == "__main__":
    main()
