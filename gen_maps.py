#!/usr/bin/env python3
"""gen_maps.py - regenerate the region map PNGs for wwigr.org.

Plots the living Top 100 as numbered red bubbles (the number is the Top
100 rank) on a tiled CartoDB Voyager basemap. The basemap carries crisp
coastlines, country borders, and country/city name labels. A faint
connector ties each bubble back to its true institution location when the
declutter step had to move the bubble.

The basemap tiles are fetched from CartoDB (public, no key) and cached on
disk under out/cache/tiles/. The Web Mercator projection of the tiles is
preserved exactly: bubbles are placed in the same global-pixel coordinate
system as the stitched tiles, and the axis uses equal aspect, so there is
no horizontal/vertical skew.

Usage:  python gen_maps.py            generate all maps
        python gen_maps.py 0|1|2|3    generate one map (world/NA/EU/Asia)

Output: _site/img/10_top100_overview.png and 11/12/13 regional PNGs.
"""
import csv, glob, io, math, os, sys, time, urllib.request
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
SITE = Path(os.environ.get("WWIGR_SITE", ROOT / "_site"))
UP = ROOT.parent
DOT = "#b2243a"
MANUAL_GEO = {"university of waikato": (-37.788, 175.317),
              "kennesaw state university": (33.9396, -84.5197)}
TILE = 256
TILE_CACHE = UP / "out" / "cache" / "tiles"
TILE_STYLE = "rastertiles/voyager"       # CartoDB Voyager: borders + labels
TILE_SUBDOMAINS = ("a", "b", "c", "d")
USER_AGENT = "wwigr-map-builder/1.0 (admin@wwigr.org)"


def norm(s):
    return " ".join((s or "").strip().lower().split())


# ---- Web Mercator global-pixel helpers (slippy-tile convention) -------------
def lonlat_to_px(lon, lat, z):
    """Global pixel coords at zoom z. y increases southward (tile convention)."""
    n = float(2 ** z)
    lat = max(min(lat, 85.05112878), -85.05112878)
    latr = math.radians(lat)
    x = (lon + 180.0) / 360.0 * n * TILE
    y = (1.0 - math.log(math.tan(latr) + 1.0 / math.cos(latr)) / math.pi) / 2.0 * n * TILE
    return x, y


def _fetch_tile(z, x, y):
    n = 2 ** z
    if not (0 <= x < n and 0 <= y < n):
        return Image.new("RGB", (TILE, TILE), (255, 255, 255))
    TILE_CACHE.mkdir(parents=True, exist_ok=True)
    cache = TILE_CACHE / f"{TILE_STYLE.replace('/', '_')}_{z}_{x}_{y}.png"
    if cache.exists():
        return Image.open(cache).convert("RGB")
    sub = TILE_SUBDOMAINS[(x + y) % len(TILE_SUBDOMAINS)]
    url = f"https://{sub}.basemaps.cartocdn.com/{TILE_STYLE}/{z}/{x}/{y}.png"
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            data = urllib.request.urlopen(req, timeout=20).read()
            cache.write_bytes(data)
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(0.6 * (attempt + 1))
    print(f"    tile {z}/{x}/{y} failed: {last}")
    return Image.new("RGB", (TILE, TILE), (255, 255, 255))


def basemap(lon0, lon1, lat0, lat1, z):
    """Return (PIL image, (px_left, px_top, px_right, px_bottom)) for the bbox."""
    x_left, y_top = lonlat_to_px(lon0, lat1, z)      # NW corner
    x_right, y_bot = lonlat_to_px(lon1, lat0, z)     # SE corner
    tx0, tx1 = int(x_left // TILE), int(x_right // TILE)
    ty0, ty1 = int(y_top // TILE), int(y_bot // TILE)
    W = (tx1 - tx0 + 1) * TILE
    H = (ty1 - ty0 + 1) * TILE
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            canvas.paste(_fetch_tile(z, tx, ty), ((tx - tx0) * TILE, (ty - ty0) * TILE))
    ox, oy = tx0 * TILE, ty0 * TILE
    crop = (int(round(x_left - ox)), int(round(y_top - oy)),
            int(round(x_right - ox)), int(round(y_bot - oy)))
    img = canvas.crop(crop)
    return img, (x_left, y_top, x_right, y_bot)


# ---- data loading -----------------------------------------------------------
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


def declutter(pos, min_sep, iters=140):
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


# ---- drawing ----------------------------------------------------------------
def draw(pts, extent, title, outpath, figsize, zoom):
    lon0, lon1, lat0, lat1 = extent
    img, (px_l, px_t, px_r, px_b) = basemap(lon0, lon1, lat0, lat1, zoom)

    fig, ax = plt.subplots(figsize=figsize)
    # data coords == global pixel coords; y inverted so north is up.
    ax.imshow(img, extent=[px_l, px_r, px_b, px_t], origin="upper",
              interpolation="bilinear", zorder=0)
    ax.set_xlim(px_l, px_r)
    ax.set_ylim(px_b, px_t)            # inverted (px_b > px_t): south at bottom
    ax.set_aspect("equal")            # no skew

    inside = []
    for rank, lat, lon in pts:
        x, y = lonlat_to_px(lon, lat, zoom)
        if px_l <= x <= px_r and px_t <= y <= px_b:
            inside.append((rank, x, y))

    span = px_r - px_l
    true_xy = [(x, y) for _, x, y in inside]
    label_xy = [[x, y] for _, x, y in inside]
    declutter(label_xy, min_sep=span * 0.038)

    for (tx, ty), (lx, ly) in zip(true_xy, label_xy):
        if math.hypot(lx - tx, ly - ty) > span * 0.012:
            ax.plot([tx, lx], [ty, ly], color="#444444", lw=0.6, zorder=4)
            ax.scatter([tx], [ty], s=8, c="#444444", zorder=4)
    ax.scatter([p[0] for p in label_xy], [p[1] for p in label_xy],
               s=150, c=DOT, edgecolors="white", linewidths=1.0, zorder=6)
    for (rank, _, _), (lx, ly) in zip(inside, label_xy):
        t = ax.text(lx, ly, str(rank), fontsize=6.6 if rank < 100 else 5.6,
                    fontweight="bold", ha="center", va="center",
                    color="white", zorder=7)
        t.set_path_effects([pe.withStroke(linewidth=0.6, foreground="#7a0f1e")])

    ax.set_axis_off()
    ax.set_title(title, fontsize=15, color="#003366", fontweight="bold", pad=8)
    fig.savefig(outpath, dpi=145, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {outpath.name}  ({len(inside)} numbered dots)")


# ---- region definitions -----------------------------------------------------
NA_COUNTRIES = {"US", "CA", "MX"}
EU_COUNTRIES = {
    "AD","AL","AT","BA","BE","BG","BY","CH","CY","CZ","DE","DK","EE","ES",
    "FI","FO","FR","GB","GR","HR","HU","IE","IS","IT","LI","LT","LU","LV",
    "MC","MD","ME","MK","MT","NL","NO","PL","PT","RO","RS","RU","SE","SI",
    "SK","SM","TR","UA","VA","XK",
}
AS_COUNTRIES = {
    "AF","AM","AU","AZ","BD","BN","BT","CN","GE","HK","ID","IN","JP","KG",
    "KH","KP","KR","KZ","LA","LK","MM","MN","MO","MV","MY","NP","NZ","PG",
    "PH","PK","SG","TH","TJ","TL","TM","TW","UZ","VN","FJ",
}
# (extent lon0,lon1,lat0,lat1), title, filename, figsize, tile-zoom, country set
MAPS = [
    ((-170, 180, -48, 72), "Top 100 Goldbach researchers worldwide",
     "10_top100_overview.png", (13, 6.6), 3, None),
    ((-126, -62, 25, 52), "Top 100 researchers in North America",
     "11_top100_north_america.png", (11, 5.6), 4, NA_COUNTRIES),
    ((-11, 38, 34, 62), "Top 100 researchers in Europe",
     "12_top100_europe.png", (10, 7.0), 5, EU_COUNTRIES),
    ((58, 180, -45, 56), "Top 100 researchers in Asia and the Pacific",
     "13_top100_asia.png", (13, 6.6), 4, AS_COUNTRIES),
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
    which = ([int(sys.argv[1])] if len(sys.argv) > 1 else range(len(MAPS)))
    for idx in which:
        extent, title, fn, figsize, zoom, cset = MAPS[idx]
        if cset is None:
            sub = [(r, lat, lon) for r, lat, lon, c in pts]
        else:
            sub = [(r, lat, lon) for r, lat, lon, c in pts if c in cset]
        draw(sub, extent, title, SITE / "img" / fn, figsize, zoom)
    print("done")


if __name__ == "__main__":
    main()
