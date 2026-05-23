#!/usr/bin/env python3
"""gen_maps.py - regenerate the four region map PNGs for wwigr.org.

Plots the living Top 100 researchers (one dot per researcher, located by
their institution via the geocode cache) on a world map and three
regional maps. Output PNGs are written into _site/img/. Run after a data
refresh; publish.py does not touch the maps.

Inputs:  ../out/gb_top100_*.csv, ../out/gb_next100_*.csv,
         ../out-wd/gb_wikidata_enrich_*.csv, ./data_overrides.csv,
         ../out/cache/gb_affiliations_geocoded.csv, ./world_110m.geojson
Outputs: _site/img/10_top100_overview.png and 11/12/13 regional PNGs
"""
import csv, glob, json, math, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"
UP = ROOT.parent
LAND, LAND_EDGE, OCEAN, DOT = "#e6e6e0", "#ffffff", "#f2f6f9", "#b2243a"
# institutions absent from the geocode cache
MANUAL_GEO = {"university of waikato": (-37.788, 175.317)}


def norm(s):
    return " ".join((s or "").strip().lower().split())


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
        death = o.get("death_date") or enr.get(r["name"], "")
        r["_dead"] = bool(death)
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


def load_polys():
    gj = json.load(open(ROOT / "world_110m.geojson", encoding="utf-8"))
    polys = []
    for feat in gj["features"]:
        g = feat.get("geometry")
        if not g:
            continue
        if g["type"] == "Polygon":
            polys.append(g["coordinates"][0])
        elif g["type"] == "MultiPolygon":
            for part in g["coordinates"]:
                polys.append(part[0])
    return polys


def draw(polys, pts, extent, title, outpath, figsize):
    lon0, lon1, lat0, lat1 = extent
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_facecolor(OCEAN)
    pc = PatchCollection([MplPolygon(r, closed=True) for r in polys],
                         facecolor=LAND, edgecolor=LAND_EDGE, linewidths=0.4)
    ax.add_collection(pc)
    if pts:
        ax.scatter([p[1] for p in pts], [p[0] for p in pts],
                   s=46, c=DOT, edgecolors="white", linewidths=0.7,
                   alpha=0.80, zorder=5)
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    midlat = math.radians((lat0 + lat1) / 2)
    ax.set_aspect(1.0 / max(math.cos(midlat), 0.2))
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, fontsize=15, color="#003366", fontweight="bold", pad=10)
    fig.savefig(outpath, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {outpath.name}  ({len(pts)} dots)")


def main():
    living = load_living()
    geo = load_geo()
    polys = load_polys()
    pts, missed = [], []
    for r in living:
        key = norm(r["institution"])
        ll = geo.get(key) or MANUAL_GEO.get(key)
        if ll:
            jx = random.Random(r["name"]).uniform(-0.35, 0.35)
            jy = random.Random(r["name"] + "y").uniform(-0.35, 0.35)
            pts.append((ll[0] + jy, ll[1] + jx))
        else:
            missed.append(r["institution"])
    print(f"living Top 100: {len(living)}; geocoded {len(pts)}; "
          f"no geocode {len(missed)}")
    if missed:
        print("  not geocoded:", "; ".join(sorted(set(missed))[:12]))
    img = SITE / "img"
    img.mkdir(parents=True, exist_ok=True)
    draw(polys, pts, (-168, 188, -52, 78),
         "Top 100 Goldbach researchers worldwide",
         img / "10_top100_overview.png", (12, 6.0))
    draw(polys, pts, (-170, -52, 12, 72),
         "Top 100 researchers in North America",
         img / "11_top100_north_america.png", (9, 7.2))
    draw(polys, pts, (-12, 42, 34, 71),
         "Top 100 researchers in Europe",
         img / "12_top100_europe.png", (8.5, 7.2))
    draw(polys, pts, (25, 182, -48, 56),
         "Top 100 researchers in Asia and Oceania",
         img / "13_top100_asia.png", (12, 6.4))
    print("done")


if __name__ == "__main__":
    main()
