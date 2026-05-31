#!/usr/bin/env python3
"""publish.py - single-source generator for the wwigr.org static site.

One run of `python publish.py` regenerates every data-driven page in
_site/ from the upstream R-pipeline CSVs, the Wikidata enrichment, and
the website-level data files (data_overrides.csv, homepages.csv).

Data-driven pages (regenerated here):
    index.html, top100.html, regions/*.html, in-memoriam.html,
    reading-list.html, data.html, people/*.html (one per Top 100
    researcher), plus data/wwigr_top100.csv, sitemap.xml, robots.txt.

Hand-maintained static pages (NOT touched here):
    genealogy.html, about.html, methodology.html. These carry
    hand-written content (advisor notes, audit trail) that no CSV
    holds; edit them directly.

Maps: the four region PNGs are produced by the R map script; this
script only copies the latest PNGs into _site/img/.

Usage:
    python publish.py            regenerate in place
    python publish.py --check    dry run, report what would change
"""

import csv
import glob
import html
import shutil
import sys
import unicodedata
import datetime
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"
UP = ROOT.parent
BASE = "https://wwigr.org"
SITE_NAME = "Who's Who in Goldbach Research"
SITE_DESC = ("A directory of the researchers most active on the Goldbach "
             "conjecture, ranked from arXiv preprint output, OpenAlex "
             "citation data, and zbMATH MSC classifications.")
DOI_CONCEPT = "10.5281/zenodo.20355375"
DOI_URL = "https://doi.org/" + DOI_CONCEPT
VERIFY_TAG = ('<meta name="google-site-verification" '
              'content="nTo_CIJXODwXPNsVkC0oT7IYWnRXP3F8U4344Z_ylMs" />')

NA_COUNTRIES = {"US", "CA", "MX"}
# Europe set: traditional Europe only. Turkey and Israel moved to the
# Asia / Middle East / Pacific bucket so each researcher lands in
# exactly one region.
# Europe set includes Turkey (NATO, Council of Europe, UEFA, EU
# candidate). Israel and Jordan land in "Other regions" with the rest
# of the Middle East / Africa / South America tail.
EU_COUNTRIES = {
    "AD","AL","AT","BA","BE","BG","BY","CH","CY","CZ","DE","DK","EE","ES",
    "FI","FO","FR","GB","GR","HR","HU","IE","IS","IT","LI","LT","LU","LV",
    "MC","MD","ME","MK","MT","NL","NO","PL","PT","RO","RS","RU","SE","SI",
    "SK","SM","TR","UA","VA","XK",
}
# Asia and the Pacific. East/South/Central Asia and Oceania; no Middle
# East. Tajikistan stays here as Central Asia.
AS_COUNTRIES = {
    "AF","AM","AU","AZ","BD","BN","BT","CN","GE","HK","ID","IN","JP","KG",
    "KH","KP","KR","KZ","LA","LK","MM","MN","MO","MV","MY","NP","NZ","PG",
    "PH","PK","SG","TH","TJ","TL","TM","TW","UZ","VN","FJ",
}

DRY = "--check" in sys.argv

NAV_ITEMS = [
    ("index.html",                  "Home"),
    ("top100.html",                 "Top 100"),
    ("regions/north-america.html",  "North America"),
    ("regions/europe.html",         "Europe"),
    ("regions/asia.html",           "Asia & Pacific"),
    ("in-memoriam.html",            "In Memoriam"),
    ("genealogy.html",              "Genealogy"),
    ("reading-list.html",           "Reading List"),
    ("data.html",                   "Data"),
    ("methodology.html",            "Methodology"),
    ("about.html",                  "About"),
]


def esc(s):
    return html.escape(s or "", quote=True)


def slugify(name):
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    import re
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "researcher"


# Map of slugified advisor name -> profile slug, for people who have a detail
# page. Populated in main() before any detail page is rendered. Used to turn
# the "Doctoral advisor" line into links when the advisor is in our directory.
ADV_SLUG = {}


def linkify_advisors(advisor):
    """Render the advisor string, linking any advisor who has a profile page.
    Advisors are semicolon-separated in the source data. Returns "" when empty
    so callers can decide whether to show an N/A row."""
    if not advisor:
        return ""
    import re as _re
    parts = [x.strip() for x in _re.split(r"\s*;\s*", advisor) if x.strip()]
    if not parts:
        return ""
    out = []
    for nm in parts:
        sl = ADV_SLUG.get(slugify(nm))
        out.append(f'<a href="{sl}.html">{esc(nm)}</a>' if sl else esc(nm))
    return ", ".join(out)


def ascii_name(name):
    """Plain-ASCII version of the name. Strips diacritics and any
    non-ASCII characters. Used for the dataset CSV's name_ascii column
    so Excel users on default Windows code pages can read it cleanly."""
    # Letters that NFKD does not decompose (they are distinct letters,
    # not base + combining mark) need an explicit substitution.
    swaps = {
        "ł": "l", "Ł": "L",   # Polish stroked L (ł, Ł)
        "ı": "i", "İ": "I",   # Turkish dotless/dotted I (ı, İ)
        "ø": "o", "Ø": "O",   # Scandinavian O-slash (ø, Ø)
        "æ": "ae", "Æ": "Ae", # ae digraph (æ, Æ)
        "ß": "ss",                  # German sharp s (ß)
        "ð": "d", "Ð": "D",   # Icelandic/old English eth (ð, Ð)
        "þ": "th", "Þ": "Th", # thorn (þ, Þ)
    }
    s = "".join(swaps.get(c, c) for c in (name or ""))
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.encode("ascii", "ignore").decode("ascii")
    return s.strip()


def rank_cell(rank, kind):
    # A sortable <td> for a rank column. The data-order attribute carries
    # the bare number so DataTables sorts numerically even when the
    # display value is bracketed ("[24]") or a dash.
    try:
        n = int(rank)
    except (TypeError, ValueError):
        n = 9999
    if kind == "interp":
        disp = f"[{n}]"
    elif kind == "none":
        disp = "-"
    else:
        disp = str(n)
    return f'<td data-order="{n}">{disp}</td>'


def _latest(pattern):
    matches = sorted(glob.glob(str(UP / pattern)))
    if not matches:
        raise SystemExit(f"no file matched {pattern}")
    return matches[-1]


def _nav(active, depth):
    prefix = "../" if depth else "./"
    return "\n".join(
        f'<a href="{prefix}{href}" class="{"nav-active" if href == active else ""}">{label}</a>'
        for href, label in NAV_ITEMS)


def _page(title, body, active, depth=0, extra_head=""):
    css = "../styles.css" if depth else "./styles.css"
    home = "../index.html" if depth else "./index.html"
    full_title = title if title == SITE_NAME else f"{title} - {SITE_NAME}"
    canon = BASE + "/" if active == "index.html" else BASE + "/" + active[:-5]
    og = (f'<meta property="og:title" content="{esc(full_title)}">\n'
          f'<meta property="og:description" content="{esc(SITE_DESC)}">\n'
          f'<meta property="og:type" content="website">\n'
          f'<meta property="og:url" content="{canon}">\n'
          f'<meta property="og:site_name" content="{esc(SITE_NAME)}">\n'
          f'<meta name="twitter:card" content="summary">\n'
          f'<meta name="description" content="{esc(SITE_DESC)}">')
    head_extra = ("\n" + extra_head) if extra_head else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<link rel="stylesheet" href="{css}">
<link rel="stylesheet" href="https://cdn.datatables.net/2.1.8/css/dataTables.dataTables.min.css">
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/2.1.8/js/dataTables.min.js"></script>
{og}{head_extra}
</head>
<body>
<header class="site-header">
  <div class="brand"><a href="{home}">{SITE_NAME}</a></div>
  <nav>{_nav(active, depth)}</nav>
</header>
<main>
{body}
</main>
<footer>
<p>Maintained by Steve Hubbard (<a href="mailto:admin@wwigr.org">admin@wwigr.org</a>). Data sources: <a href="https://arxiv.org">arXiv</a>, <a href="https://openalex.org">OpenAlex</a>, <a href="https://zbmath.org">zbMATH Open</a>, <a href="https://www.mathgenealogy.org">Mathematics Genealogy Project</a>.</p>
<p>Last built May 2026.</p>
</footer>
</body>
</html>
"""


def _write(rel_path, content):
    target = SITE / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if DRY:
        existed = target.exists()
        same = existed and target.read_text(encoding="utf-8") == content
        print(f"  [{'ok' if same else ('new' if not existed else 'changed')}] {rel_path}")
        return
    target.write_text(content, encoding="utf-8")


def _clean(v):
    v = (v or "").strip()
    return "" if v.upper() == "NA" else v


def load_enrichment():
    matches = sorted(glob.glob(str(UP / "out-wd/gb_wikidata_enrich_*.csv")))
    enr = {}
    if matches:
        with open(matches[-1], encoding="utf-8") as f:
            for r in csv.DictReader(f):
                enr[r["name"]] = {k: _clean(r.get(k)) for k in
                                  ("death_date", "birth_year", "image", "advisor", "orcid", "qid")}
    # Overlay missing qid/orcid from zbmath.csv (zbMATH harvests these
    # external_ids reliably and tends to have them when Wikidata search
    # missed). Only fills empty fields; existing values are kept.
    zpath = ROOT / "zbmath.csv"
    if zpath.exists():
        with open(zpath, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                e = enr.setdefault(r["name"], {})
                if not e.get("qid") and (r.get("wikidata") or "").strip():
                    e["qid"] = r["wikidata"].strip()
                if not e.get("orcid") and (r.get("orcid") or "").strip():
                    e["orcid"] = r["orcid"].strip()
                # Ensure all expected keys exist
                for k in ("death_date","birth_year","image","advisor","orcid","qid"):
                    e.setdefault(k, "")
    return enr


def load_overrides():
    ov = {}
    path = ROOT / "data_overrides.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for o in csv.DictReader(f):
                ov[o["name"]] = {k: o[k].strip() for k in
                                 ("display_name", "institution", "country",
                                  "birth_date", "death_date",
                                  "first_year", "last_year")
                                 if (o.get(k) or "").strip()}
    return ov


def _oa_last_token(name):
    import re
    if not name or not name.strip(): return ""
    s = re.sub(r"[‐–—]", "-", name.strip())
    parts = s.split()
    return parts[-1].lower() if parts else ""


def load_oa_ids():
    """Return (by_name, by_surname). The by_surname entry per surname is the
    OA author_id of the OA author with that surname who has the most
    topical works (mirrors the merge step's selection). Lets profile-page
    rendering find the right OA author_id even when the canonical display
    name (e.g. "Tim Browning") doesn't equal the OA name ("T. D. Browning").
    Reads oa_overrides.csv after the master to fill names where we already
    looked up the correct OA author_id by hand (typically zb_only or
    arxiv_only entries that didn't appear in the OA top 200 master)."""
    by_name = {}
    by_surname = {}
    by_surname_works = {}
    matches = sorted(glob.glob(str(UP / "out-oa/gb_oa_master_*.csv")))
    if matches:
        with open(matches[-1], encoding="utf-8") as f:
            for r in csv.DictReader(f):
                aid = r["author_id"].rsplit("/", 1)[-1]
                by_name[r["author_name"]] = aid
                lt = _oa_last_token(r["author_name"])
                try:
                    nw = int(r["n_topical_works"])
                except (TypeError, ValueError):
                    nw = 0
                if lt and (lt not in by_surname or nw > by_surname_works[lt]):
                    by_surname[lt] = aid
                    by_surname_works[lt] = nw
    # Overlay manual overrides (these win over the master)
    ov_path = ROOT / "oa_overrides.csv"
    if ov_path.exists():
        with open(ov_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("name") and r.get("oa_author_id"):
                    by_name[r["name"]] = r["oa_author_id"].strip()
    return by_name, by_surname


def load_homepages():
    hp = {}
    path = ROOT / "homepages.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("url") or "").strip():
                    hp[r["name"]] = r["url"].strip()
    return hp


def load_scholar():
    sc = {}
    path = ROOT / "scholar.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("url") or "").strip():
                    sc[r["name"]] = r["url"].strip()
    return sc


def load_zbmath():
    """Return name -> canonical zbMATH URL (and code) for any author we
    were able to resolve via the REST API."""
    zb = {}
    path = ROOT / "zbmath.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("zbmath_url") or "").strip():
                    zb[r["name"]] = {
                        "url": r["zbmath_url"].strip(),
                        "code": (r.get("code") or "").strip(),
                    }
    return zb


def load_hindex():
    h = {}
    path = ROOT / "hindex.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                v = (r.get("h_index") or "").strip()
                if v.isdigit():
                    h[r["name"]] = {
                        "h": int(v),
                        "source": (r.get("source") or "").strip(),
                    }
    return h


def load_genealogy():
    path = ROOT / "genealogy.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def scholar_search_url(name):
    import re
    base = re.sub(r"\s*\([^)]*\)", "", name or "").strip()
    q = urllib.parse.quote_plus(base + " number theory")
    return "https://scholar.google.com/scholar?q=" + q


# Per-person arXiv author-search query overrides (display name -> exact query).
ARXIV_QUERY_OVERRIDE = {"H. J. Weber": "Weber, H J"}
def arxiv_search_url(name):
    import re
    key = (name or "").strip()
    if key in ARXIV_QUERY_OVERRIDE:
        base = ARXIV_QUERY_OVERRIDE[key]
    else:
        base = re.sub(r"\s*\([^)]*\)", "", name or "").strip()
    q = urllib.parse.quote_plus(base)
    return f"https://arxiv.org/search/?searchtype=author&query={q}"


def zbmath_search_url(name):
    """Build a zbMATH author-search URL.

    zbMATH has canonical author pages at /authors/surname.firstname but its
    API is gated behind a Terms-of-Use prompt that blocks automated lookup.
    A name search reliably lands on the canonical page when there is a
    unique match and on a short list of candidates otherwise.
    """
    import re
    base = re.sub(r"\s*\([^)]*\)", "", name or "").strip()
    q = urllib.parse.quote_plus(base)
    return f"https://zbmath.org/authors/?q={q}"


def load_pool():
    rows = []
    for pat in ("out/gb_top100_*.csv", "out/gb_next100_*.csv"):
        path = _latest(pat)
        print(f"reading {path}")
        with open(path, encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    enr = load_enrichment()
    ov = load_overrides()
    for r in rows:
        o = ov.get(r["name"], {})
        r["_orig_name"] = r["name"]
        if "display_name" in o:
            r["name"] = o["display_name"]
        if "institution" in o:
            r["institution"] = o["institution"]
        if "country" in o:
            r["country"] = o["country"]
        if o.get("first_year"):
            r["first_year"] = o["first_year"]
        if o.get("last_year"):
            r["last_year"] = o["last_year"]
        e = enr.get(r["name"], {})
        r["_enr"] = e
        death = o.get("death_date") or e.get("death_date") or ""
        birth = o.get("birth_date") or e.get("birth_year") or ""
        r["death_date"] = death
        r["birth_date"] = birth
        r["status"] = "deceased" if death else "living"
    return rows


def render_top100(rows, hindex):
    body_rows = []
    for r in sorted(rows, key=lambda r: r["display_rank"]):
        arx_c = rank_cell(r.get("arx_rank"), r.get("arx_kind", "real"))
        oa_c = rank_cell(r.get("oa_rank"), r.get("oa_kind", "real"))
        zb_c = rank_cell(r.get("zb_rank"), r.get("zb_kind", "real"))
        h = hindex.get(r["name"])
        h_val = h["h"] if h else ""
        h_cell = f'<td data-order="{h_val if h_val != "" else -1}">{h_val}</td>'
        name = f'<a href="people/{r["slug"]}.html">{esc(r["name"])}</a>'
        body_rows.append(
            f"<tr><td>{r['display_rank']}</td><td>{name}</td>"
            f"<td>{esc(r['institution'])}</td><td>{esc(r['country'])}</td>"
            f"{arx_c}{oa_c}{zb_c}{h_cell}<td>{esc(r['provenance'])}</td>"
            f"<td>{r['first_year']}</td><td>{r['last_year']}</td></tr>")
    prov = Counter(r["provenance"] for r in rows)
    prov_rows = "".join(
        f"<tr><td><code>{esc(k)}</code></td><td style='text-align:right'>{v}</td></tr>"
        for k, v in prov.most_common())
    body = f"""<h1>The Top 100</h1>
<p class="subtitle">Researchers active on Goldbach and adjacent problems</p>

<p>The list is sortable on any column. Type in the search box to filter by name, institution, or country. Click any name for that researcher's profile page.</p>

<p>This page shows the 100 highest-ranked living researchers, renumbered 1 to 100. Researchers in the ranked pool who have passed away are remembered on the <a href="in-memoriam.html">In Memoriam</a> page.</p>

<p class="callout"><strong>Reading the columns.</strong> <em>arXiv rank</em>, <em>OA rank</em>, and <em>zbMATH rank</em> are the researcher's position in the full composite score for each of three pipelines. For arXiv and OpenAlex a keyword match in a paper title counts at full weight and an abstract-only mention at half (A=0.5), so papers that only cite Goldbach in passing are discounted; each composite is then 60% weighted paper count + 40% network or citation signal, over arXiv (137 qualifying authors across 17 search terms) and OpenAlex (572 authors across 13 phrase queries). zbMATH (495 authors) uses the three Goldbach-core MSC classes 11P32, 11P55 and 11N36. The overall rank combines the three with a weighted order statistic, 70/20/10 on each researcher's best, middle and worst of the three ranks, so lower is better in every column and a single dominant Goldbach pipeline can carry a researcher (the top weight only ever lands on a measured rank). A value in [square brackets] is interpolated: the researcher did not appear in that pipeline directly, so their rank there is estimated from their position in the others. See the <a href="methodology.html">methodology</a> for how. A dash means no estimate was possible.</p>

<table id="top100tbl" class="display compact stripe hover" style="width:100%">
<thead><tr><th>Rank</th><th>Name</th><th>Institution</th><th>Country</th><th>arXiv rank</th><th>OA rank</th><th>zbMATH rank</th><th>h-index</th><th>Source</th><th>First year</th><th>Last year</th></tr></thead>
<tbody>
{chr(10).join(body_rows)}
</tbody>
</table>
<script>
$(document).ready(function() {{
  $('#top100tbl').DataTable({{ pageLength: 25, lengthMenu: [25, 50, 100], order: [[0, 'asc']] }});
}});
</script>

<p class="muted">Ranks shown in [square brackets] are interpolated estimates, not measured values. <a href="methodology.html">How interpolation works</a>.</p>

<h2>Source column legend</h2>
<p>The <strong>Source</strong> column records which of the three pipelines ranked each researcher directly. Where a pipeline did not rank someone, the rank shown for that pipeline is an interpolated estimate (in [square brackets]).</p>
<ul>
<li><code>all_three</code>: ranked directly by arXiv, OpenAlex, and zbMATH. The unanimous core.</li>
<li><code>arx+oa</code>: ranked by arXiv and OpenAlex, but not zbMATH.</li>
<li><code>arx+zb</code>: ranked by arXiv and zbMATH, but not OpenAlex.</li>
<li><code>oa+zb</code>: ranked by OpenAlex and zbMATH, but not arXiv.</li>
<li><code>arxiv_only</code>: ranked only by the arXiv pipeline.</li>
<li><code>oa_only</code>: ranked only by OpenAlex. Often senior figures who publish in journals and do not post preprints.</li>
<li><code>zb_only</code>: ranked only by zbMATH. Often pre-1995 Russian and Chinese number theorists that arXiv and OpenAlex under-index.</li>
</ul>

<table><thead><tr><th>Source</th><th>Count</th></tr></thead><tbody>{prov_rows}</tbody></table>

<h2>Limitations</h2>
<p>This list reflects publication output and citation network density, not subjective importance. A starting point, not a verdict.</p>
"""
    _write("top100.html", _page("The Top 100", body, "top100.html"))


def render_region(rows, slug, title, countries, png, blurb):
    rs = sorted([r for r in rows if r["country"] in countries],
                key=lambda r: r["display_rank"])
    body_rows = "\n".join(
        f"<tr><td>{r['display_rank']}</td>"
        f"<td><a href=\"../people/{r['slug']}.html\">{esc(r['name'])}</a></td>"
        f"<td>{esc(r['institution'])}</td><td>{esc(r['country'])}</td></tr>"
        for r in rs)
    verb = "researcher is" if len(rs) == 1 else "researchers are"
    map_html = ""
    if slug != "other" and png and (SITE / "img" / png).exists():
        map_html = (f'<div class="figure-page">\n'
                    f'<img src="../img/{png}" alt="Map of {esc(title)} '
                    f'Top 100 researchers">\n</div>\n')
    body = f"""<h1>{esc(title)}</h1>
<p class="subtitle">Top 100 researchers based in {esc(title)}</p>

<p>{len(rs)} of the Top 100 {verb} based in {esc(title)}.</p>

{map_html}
<h2>Listing</h2>
<table id="rtbl" class="display compact stripe hover" style="width:100%">
<thead><tr><th>Rank</th><th>Name</th><th>Institution</th><th>Country</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
<script>
$(document).ready(function() {{
  $('#rtbl').DataTable({{ pageLength: 25, lengthMenu: [25, 50, 100], order: [[0, 'asc']] }});
}});
</script>
"""
    active = f"regions/{slug}.html"
    _write(active, _page(title, body, active, depth=1))



def _full_detail_rows(*, name, orig_name=None, homepage=None, scholar_url=None,
                      oaid=None, zb=None, born=None, advisor=None,
                      arx_papers=None, oa_works=None, oa_cites=None,
                      active_years=None, hindex_entry=None, orcid=None,
                      extra=None):
    """Build the standard profile metric rows for any person, the same set of
    fields the Top 100 pages use. Missing values render as N/A."""
    orig = orig_name or name
    out = []

    def add(label, val):
        out.append(f"<tr><td>{label}</td>"
                   f"<td>{val if val not in (None, '', 'NA') else 'N/A'}</td></tr>")

    if homepage:
        host = homepage.split("//", 1)[-1].split("/", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        add("Homepage", f'<a href="{esc(homepage)}">{esc(host)}</a>')
    else:
        add("Homepage", "N/A")
    add("arXiv", f'<a href="{esc(arxiv_search_url(orig))}">Author search</a>')
    if scholar_url:
        add("Google Scholar", f'<a href="{esc(scholar_url)}">View profile</a>')
    else:
        add("Google Scholar",
            f'<a href="{esc(scholar_search_url(name))}">Search results</a>')
    if oaid:
        add("OpenAlex", f'<a href="https://openalex.org/{oaid}">Author page</a>')
    else:
        add("OpenAlex",
            f'<a href="https://openalex.org/works?search='
            f'{urllib.parse.quote_plus(name)}">Search works</a>')
    if zb:
        add("zbMATH", f'<a href="{esc(zb["url"])}">Author page</a>')
    else:
        add("zbMATH", f'<a href="{esc(zbmath_search_url(orig))}">Author search</a>')
    add("Born", (born or "")[:4] if born else "N/A")
    add("Doctoral advisor", linkify_advisors(advisor) or "N/A")
    add("arXiv Goldbach-topical papers",
        arx_papers if arx_papers not in (None, "") else "N/A")
    add("OpenAlex topical works", oa_works if oa_works not in (None, "") else "N/A")
    add("OpenAlex topical citations",
        oa_cites if oa_cites not in (None, "") else "N/A")
    add("Active years", active_years or "N/A")
    if hindex_entry:
        src = "OpenAlex" if hindex_entry["source"] == "openalex" else "Google Scholar"
        add("Overall h-index",
            f'{hindex_entry["h"]} <span class="muted">({src})</span>')
    else:
        add("Overall h-index", "N/A")
    if orcid:
        add("ORCID", f'<a href="https://orcid.org/{orcid}">{esc(orcid)}</a>')
    else:
        add("ORCID", "N/A")
    for label, val in (extra or []):
        add(label, val)
    return "\n".join(out)


def _write_detail(slug, name, subtitle, back_href, back_label,
                  intro_html, rows_html, bottom_html):
    body = f"""<p class="subtitle"><a href="../{back_href}">&larr; {back_label}</a></p>
<h1>{esc(name)}</h1>
<p class="subtitle">{subtitle}</p>
{intro_html}
<table class="profile-table">
<tbody>
{rows_html}
</tbody>
</table>
{bottom_html}
<p class="callout">Spotted an error or an omission? Email <a href="mailto:admin@wwigr.org">admin@wwigr.org</a>.</p>
"""
    rel = f"people/{slug}.html"
    _write(rel, _page(name, body, rel, depth=1))


def _oaid_for(name, orig_name, oa_by_name, oa_by_surname):
    return (oa_by_name.get(name)
            or oa_by_name.get(orig_name or "")
            or oa_by_surname.get(_oa_last_token(orig_name or name)))


def render_inmemoriam(deceased, oa_by_name, oa_by_surname, homepages, scholar, hindex, zbmath, used_slugs):
    rows = sorted(deceased, key=lambda r: r.get("death_date") or "")

    def years(r):
        b = (r.get("birth_date") or "")[:4]
        d = (r.get("death_date") or "")[:4]
        return f"{b}-{d}" if b and d else (f"d. {d}" if d else "")

    # Load foundational figures up front so their slugs can be reserved and
    # registered for advisor-linking before any detail page is written.
    extras = []
    ex_path = ROOT / "inmemoriam_extras.csv"
    if ex_path.exists():
        with open(ex_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                extras.append(r)
    extras.sort(key=lambda r: int(r.get("birth") or 0))

    # Reserve a slug for every In Memoriam profile (deceased + foundational)
    # and register it in ADV_SLUG so doctoral-advisor lines on any page can
    # link to those who have a profile here.
    for r in list(rows) + extras:
        sl = slugify(r["name"])
        while sl in used_slugs:
            sl += "-x"
        used_slugs.add(sl)
        r["slug"] = sl
        ADV_SLUG.setdefault(slugify(r["name"]), sl)

    # Detail pages for the ranked-pool deceased.
    for r in rows:
        e = r.get("_enr", {})
        fy, ly = r.get("first_year", ""), r.get("last_year", "")
        active = f"{fy} to {ly}" if fy and ly else ""
        rows_html = _full_detail_rows(
            name=r["name"], orig_name=r.get("_orig_name"),
            homepage=homepages.get(r["name"]),
            scholar_url=scholar.get(r["name"]),
            oaid=_oaid_for(r["name"], r.get("_orig_name"), oa_by_name, oa_by_surname),
            zb=zbmath.get(r["name"]) or zbmath.get(r.get("_orig_name", "")),
            born=r.get("birth_date"), advisor=e.get("advisor"),
            arx_papers=r.get("arx_papers"), oa_works=r.get("oa_works"),
            oa_cites=r.get("oa_cites"), active_years=active,
            hindex_entry=hindex.get(r["name"]), orcid=e.get("orcid"))
        life = years(r)
        sub = f"{esc(r['institution'])} ({esc(r['country'])})" + (f" &middot; {life}" if life else "")
        intro = ('<p>A researcher from the ranked pool of this directory who has '
                 'since passed away. The Top 100 and the regional pages list '
                 'living researchers only, so this profile preserves the record '
                 'of their place in the field.</p>')
        _write_detail(r["slug"], r["name"], sub, "in-memoriam.html",
                      "Back to In Memoriam", intro, rows_html, "")

    body_rows = "\n".join(
        f'<tr><td><a href="people/{esc(r["slug"])}.html">{esc(r["name"])}</a></td>'
        f"<td>{esc(r['institution'])}</td>"
        f"<td>{esc(r['country'])}</td><td>{years(r)}</td></tr>"
        for r in rows)

    # Detail pages for the foundational figures (sparse; mostly N/A).
    for r in extras:
        rows_html = _full_detail_rows(
            name=r["name"],
            homepage=homepages.get(r["name"]),
            scholar_url=scholar.get(r["name"]),
            oaid=_oaid_for(r["name"], None, oa_by_name, oa_by_surname),
            zb=zbmath.get(r["name"]),
            born=r.get("birth"), advisor=None,
            arx_papers=None, oa_works=None, oa_cites=None, active_years=None,
            hindex_entry=hindex.get(r["name"]), orcid=None)
        life = f"{esc(r.get('birth',''))}-{esc(r.get('death',''))}"
        sub = f"{esc(r['institution'])} ({esc(r['country'])}) &middot; {life}"
        intro = ('<p>A foundational figure in Goldbach and additive prime number '
                 'theory whose career predates the arXiv and OpenAlex digital '
                 'record this directory is built from. Listed here so the lineage '
                 'behind the modern field stays visible.</p>')
        bottom = f"<p>{esc(r.get('note',''))}</p>" if r.get("note") else ""
        _write_detail(r["slug"], r["name"], sub, "in-memoriam.html",
                      "Back to In Memoriam", intro, rows_html, bottom)

    extras_rows = "\n".join(
        f'<tr><td><a href="people/{esc(r["slug"])}.html">{esc(r["name"])}</a></td>'
        f"<td>{esc(r['institution'])}</td>"
        f"<td>{esc(r['country'])}</td><td>{esc(r.get('birth',''))}-{esc(r.get('death',''))}</td>"
        f"<td>{esc(r.get('note',''))}</td></tr>"
        for r in extras)
    extras_section = (f"""
<h2>Foundational figures</h2>

<p>The pipeline behind this site ranks researchers whose work appears on arXiv or in OpenAlex, which mostly means careers active from the mid-1990s onward. The names below predate that coverage. Their work is the bedrock on which modern Goldbach research is built; every modern paper in this directory ultimately rests on the circle method (Hardy-Littlewood, Vinogradov, van der Corput), the sieve toolkit (Halberstam-Richert, Linnik), and the breakthroughs of Chen Jingrun, Wang Yuan, and Hua Loo-Keng. They are listed in birth order. Click any name for a full profile.</p>

<table class="display compact stripe" style="width:100%">
<thead><tr><th>Name</th><th>Institution</th><th>Country</th><th>Years</th><th>Contribution</th></tr></thead>
<tbody>
{extras_rows}
</tbody>
</table>
""") if extras else ""

    body = f"""<h1>In Memoriam</h1>
<p class="subtitle">Researchers in this directory who are no longer with us</p>

<p>The Top 100 and the regional pages list living researchers only, so the directory stays accurate for anyone using it to make contact. This page remembers the {len(rows)} researchers from the ranked pool who have passed away, plus a separate listing of foundational figures whose careers predate the digital publication record our pipeline reads from. Each name links to a full profile.</p>

<h2>From the ranked pool</h2>

<table class="display compact stripe" style="width:100%">
<thead><tr><th>Name</th><th>Institution</th><th>Country</th><th>Years</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
{extras_section}
<p class="callout">A researcher missing here, or listed here in error? Email <a href="mailto:admin@wwigr.org">admin@wwigr.org</a> and it will be corrected.</p>
"""
    _write("in-memoriam.html", _page("In Memoriam", body, "in-memoriam.html"))


def _inst_country(r):
    i=esc(r.get("institution","")); c=esc(r.get("country",""))
    if i and c: return f"{i} ({c})"
    return i or c or ""


def render_profiles(people, oa_by_name, oa_by_surname, homepages, scholar, hindex, zbmath):
    for r in people:
        e = r.get("_enr", {})
        meta = []

        def add(label, val):
            if val not in (None, "", "NA"):
                meta.append(f"<tr><td>{label}</td><td>{val}</td></tr>")

        # Homepage row (always first)
        hp = homepages.get(r["name"])
        if hp:
            host = hp.split("//", 1)[-1].split("/", 1)[0]
            if host.startswith("www."):
                host = host[4:]
            add("Homepage", f'<a href="{esc(hp)}">{esc(host)}</a>')
        else:
            add("Homepage", "N/A")

        # Reference links in alphabetic order: arXiv, Google Scholar,
        # OpenAlex, zbMATH. Each gives a canonical author page when we
        # have one, otherwise a search-results link.
        add("arXiv",
            f'<a href="{esc(arxiv_search_url(r.get("_orig_name") or r["name"]))}">'
            f'Author search</a>')
        sch = scholar.get(r["name"])
        if sch:
            add("Google Scholar", f'<a href="{esc(sch)}">View profile</a>')
        else:
            add("Google Scholar",
                f'<a href="{esc(scholar_search_url(r["name"]))}">Search results</a>')
        # Look up OA author id: try the canonical display name first, then
        # the original (pre-override) name, then the surname.
        oaid = (oa_by_name.get(r["name"])
                or oa_by_name.get(r.get("_orig_name", ""))
                or oa_by_surname.get(_oa_last_token(r.get("_orig_name") or r["name"])))
        if oaid:
            add("OpenAlex",
                f'<a href="https://openalex.org/{oaid}">Author page</a>')
        else:
            add("OpenAlex",
                f'<a href="https://openalex.org/works?search={urllib.parse.quote_plus(r["name"])}">'
                f'Search works</a>')
        zb = zbmath.get(r["name"]) or zbmath.get(r.get("_orig_name", ""))
        if zb:
            add("zbMATH", f'<a href="{esc(zb["url"])}">Author page</a>')
        else:
            add("zbMATH",
                f'<a href="{esc(zbmath_search_url(r.get("_orig_name") or r["name"]))}">'
                f'Author search</a>')

        # Bio + metrics rows
        add("Born", (r.get("birth_date") or "")[:4])
        add("Doctoral advisor", linkify_advisors(e.get("advisor")))
        add("arXiv Goldbach-topical papers", r.get("arx_papers"))
        add("OpenAlex topical works", r.get("oa_works"))
        add("OpenAlex topical citations", r.get("oa_cites"))
        if r.get("first_year") and r.get("last_year"):
            add("Active years", f"{r['first_year']} to {r['last_year']}")
        else:
            add("Active years", "N/A")
        h = hindex.get(r["name"])
        if h:
            src_label = "OpenAlex" if h["source"] == "openalex" else "Google Scholar"
            add("Overall h-index", f'{h["h"]} <span class="muted">({src_label})</span>')
        orcid = e.get("orcid") or ""
        if orcid:
            add("ORCID", f'<a href="https://orcid.org/{orcid}">{orcid}</a>')

        links_html = ""  # OpenAlex link moved into the table

        body = f"""<p class="subtitle"><a href="../top100.html">&larr; Back to the Top 100</a></p>
<h1>{esc(r['name'])} (#{r['display_rank']})</h1>
<p class="subtitle">{_inst_country(r)}</p>

<table class="profile-table">
<tbody>
{chr(10).join(meta)}
</tbody>
</table>
{links_html}
<p class="callout">Profile data is compiled from arXiv, OpenAlex, zbMATH, Wikidata, and Google Scholar, with the homepage link from a web search. Spotted an error or an omission? Email <a href="mailto:admin@wwigr.org">admin@wwigr.org</a>.</p>
"""
        rel = f"people/{r['slug']}.html"
        _write(rel, _page(r["name"], body, rel, depth=1))
    n_hp = sum(1 for r in people if homepages.get(r['name']))
    n_sc = sum(1 for r in people if scholar.get(r['name']))
    print(f"  {len(people)} profile pages "
          f"({n_hp} with a homepage, {n_sc} with a Scholar profile)")


def render_acknowledged(oa_by_name, oa_by_surname, homepages, scholar, hindex, zbmath):
    """Full detail pages for people acknowledged on the About page who are not
    in the current Top 100, so the acknowledgement can link to a real profile.
    The pages are kept (linked from about.html) but not listed in the ranking."""
    people = []  # Steven J. Miller removed 2026-05-31 at his request (not on list, no acknowledgment).
    for r in people:
        rows_html = _full_detail_rows(
            name=r["name"],
            homepage=homepages.get(r["name"]),
            scholar_url=scholar.get(r["name"]),
            oaid=_oaid_for(r["name"], None, oa_by_name, oa_by_surname),
            zb=zbmath.get(r["name"]),
            born=None, advisor=None,
            arx_papers=r.get("arx_papers"), oa_works=None, oa_cites=None,
            active_years=None, hindex_entry=hindex.get(r["name"]), orcid=None)
        sub = f"{esc(r['institution'])} ({esc(r['country'])})"
        intro = ('<p>Referenced from the <a href="../about.html">Acknowledgements</a>. '
                 'This researcher is not in the current Top 100 ranking; the profile '
                 'is kept because of their contribution to the project.</p>')
        _write_detail(r["slug"], r["name"], sub, "about.html",
                      "Back to About", intro, rows_html, "")
    print(f"  {len(people)} acknowledged profile page(s)")


def render_genealogy_profiles(people, top_slugs, oa_by_name, oa_by_surname,
                              homepages, scholar, hindex, zbmath, used_slugs):
    if not people:
        return
    made = 0
    for r in people:
        if r["slug"] in top_slugs:
            continue  # now a Top 100 member; their profile owns the slug
        used_slugs.add(r["slug"])
        lifespan = (r.get("lifespan") or "").strip()
        born = lifespan[:4] if lifespan else None
        extra = []
        if r.get("phd_year"):
            extra.append(("PhD year", r.get("phd_year")))
        if lifespan:
            extra.append(("Lifespan", lifespan))
        if r.get("rank"):
            extra.append(("Close-relation rank", f'{r.get("rank")} of {len(people)}'))
        if r.get("ppr"):
            extra.append(("Network proximity (connectivity score)", r.get("ppr")))
        rows_html = _full_detail_rows(
            name=r["name"],
            homepage=homepages.get(r["name"]),
            scholar_url=(r.get("scholar_url") or "").strip() or scholar.get(r["name"]),
            oaid=_oaid_for(r["name"], None, oa_by_name, oa_by_surname),
            zb=zbmath.get(r["name"]),
            born=born, advisor=None,
            arx_papers=None, oa_works=None, oa_cites=None, active_years=None,
            hindex_entry=hindex.get(r["name"]), orcid=None, extra=extra)
        sub = esc(r.get("university") or "")
        intro = ('<p>A <strong>close relation</strong> of the Top 100: not in the '
                 'algorithmic ranking by publication count, but placed in the '
                 'immediate orbit of canonical Goldbach researchers by the '
                 "Mathematics Genealogy Project's advisor-student network.</p>")
        note = esc(r.get("note") or "")
        bottom = f"<p>{note}</p>" if note else ""
        _write_detail(r["slug"], r["name"], sub, "genealogy.html",
                      "Back to Genealogy", intro, rows_html, bottom)
        made += 1
    skipped = len(people) - made
    print(f"  {made} genealogy close-relation profile pages"
          + (f" ({skipped} now in the Top 100, skipped)" if skipped else ""))


def render_reading_list():
    matches = sorted(glob.glob(str(UP / "out-oa/gb_short_papers_*.csv")))
    if not matches:
        print("  skip reading-list")
        return
    print(f"reading {matches[-1]}")
    with open(matches[-1], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def cell(r):
        title = esc(r.get("title", ""))
        url = r.get("best_url", "")
        title_link = f'<a href="{esc(url)}">{title}</a>' if url else title
        return (f"<tr><td>{r.get('rank_placeholder', '')}</td>"
                f"<td>{esc(r.get('pages') or '?')}</td>"
                f"<td>{esc(r.get('year', ''))}</td>"
                f"<td>{esc(r.get('cites', ''))}</td>"
                f"<td>{title_link}</td>"
                f"<td>{esc((r.get('authors') or '')[:80])}</td></tr>")

    body_rows = "\n".join(cell(r) for r in rows)
    body = f"""<h1>Reading List</h1>
<p class="subtitle">Short, recent Goldbach papers (2018-2026)</p>

<p>A curated list of short Goldbach-relevant papers, sorted shortest first. The intended audience is a strong undergraduate or motivated high school student who wants to read recent research without committing to a 60-page monograph.</p>

<div class="content-block">
<p><strong>How the list was built.</strong> OpenAlex was queried for all papers matching <code>Goldbach conjecture</code>, <code>Goldbach problem</code>, or <code>Goldbach's conjecture</code> published since 2018. Filters: at most 10 authors (no physics megapapers), at most 15 pages when page count is known. Sort: shortest first, then most recent, then most cited.</p>
</div>

<p>{len(rows)} papers in total. Click any title to open the full paper.</p>

<table id="rl" class="display compact stripe hover" style="width:100%">
<thead><tr><th>#</th><th>Pages</th><th>Year</th><th>Cites</th><th>Title</th><th>Authors</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
<script>
$(document).ready(function() {{
  $('#rl').DataTable({{ pageLength: 50, lengthMenu: [25, 50, 100, 200], order: [[1, 'asc']] }});
}});
</script>
"""
    _write("reading-list.html", _page("Reading List", body, "reading-list.html"))


def render_index(rows, has_other=False):
    other_link = (', <a href="regions/other.html">Other regions</a>'
                  if has_other else "")
    by_country = Counter(r["country"] for r in rows)
    cc_rows = "".join(
        f"<tr><td>{esc(cc)}</td><td style='text-align:right'>{n}</td></tr>"
        for cc, n in by_country.most_common(8))
    body = f"""<h1>{esc(SITE_NAME)}</h1>
<p class="subtitle">A directory of researchers working on the Goldbach conjecture</p>

<div class="content-block">
<p><strong>Christian Goldbach (1690-1764)</strong> wrote a letter to Leonhard Euler in 1742 conjecturing that every even integer greater than 2 is the sum of two primes. <strong>The conjecture is still open.</strong> Nearly three centuries later, mathematicians around the world continue to chip away at it.</p>
<p>This site is a reference directory of those people. It catalogs the <strong>Top 100</strong> researchers most active on Goldbach and adjacent problems in additive prime number theory, gives their institutions, and provides a <a href="reading-list.html">curated reading list</a> of recent short papers for newcomers.</p>
</div>

<h2>How the list is built</h2>
<p>Three independent signals are combined into one composite ranking:</p>
<ol>
<li><strong>arXiv preprint output</strong> since 2003, filtered to math.NT and math.CO categories, matched against 17 Goldbach-relevant search terms.</li>
<li><strong>OpenAlex topical citations</strong> for the Goldbach phrases (<code>Goldbach conjecture</code>, <code>Goldbach problem</code>, <code>Goldbach's conjecture</code>).</li>
<li><strong>zbMATH Open</strong>, the curated mathematics review database, using the three Goldbach-core MSC subject classes (11P32 additive/Goldbach problems, 11P55 circle method, 11N36 sieve methods).</li>
</ol>
<p>The three pipeline ranks are combined with a weighted order statistic. For each researcher the three ranks are sorted and weighted 70% on the best, 20% on the middle, and 10% on the worst, so being excellent in one Goldbach pipeline counts most, while strength across all three still wins overall. Lower is better. A researcher who appears in only one or two pipelines is not penalised; the missing rank is estimated from their nearest-ranked neighbours (the 70% weight only ever falls on a real, measured rank, never an estimate). False positives and off-topic authors are explicitly excluded by hand; the approach is described in the <a href="methodology.html">methodology</a>.</p>
<p>The <a href="https://www.mathgenealogy.org">Mathematics Genealogy Project</a> supplies advisor-student relationships for the separate <a href="genealogy.html">genealogy</a> view. It does not feed the ranking.</p>

<h2>Top 100 at a glance</h2>
<p>100 researchers, drawn from {len(by_country)} countries.</p>

<table><thead><tr><th>Country</th><th>Top 100 researchers</th></tr></thead><tbody>{cc_rows}</tbody></table>

<div class="figure-page">
<img src="img/10_top100_overview.png" alt="World overview map of Top 100 Goldbach researchers">
</div>

<h2>Where to start</h2>
<ul>
<li><a href="top100.html"><strong>The Top 100</strong></a> is the canonical ranked list, sortable in your browser.</li>
<li>Regional listings: <a href="regions/north-america.html">North America</a>, <a href="regions/europe.html">Europe</a>, <a href="regions/asia.html">Asia &amp; Pacific</a>{other_link}.</li>
<li><a href="reading-list.html"><strong>Reading list</strong></a>: 2,000+ short Goldbach papers from 2018 onward, with clickable links.</li>
<li><a href="data.html"><strong>Data</strong></a>: the ranked list as an open CC-BY dataset, with a citable DOI.</li>
<li><a href="methodology.html"><strong>Methodology</strong></a>: how the data is built, audit decisions, and limitations.</li>
</ul>

<h2>Citing this site</h2>
<blockquote>Hubbard, S. (2026). <em>Who's Who in Goldbach Research</em>. Zenodo. <a href="{DOI_URL}">{DOI_URL}</a></blockquote>
"""
    _write("index.html", _page(SITE_NAME, body, "index.html", extra_head=VERIFY_TAG))


def render_data(living, enr, hindex):
    SITE.joinpath("data").mkdir(parents=True, exist_ok=True)
    cols = ["rank", "name", "name_ascii", "institution", "country",
            "arxiv_rank", "openalex_rank", "zbmath_rank",
            "arxiv_papers", "openalex_works", "openalex_citations", "zbmath_papers",
            "overall_h_index", "h_index_source", "first_active_year",
            "last_active_year", "birth_year", "doctoral_advisor", "orcid",
            "wikidata_id"]
    if not DRY:
        with open(SITE / "data/wwigr_top100.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in living:
                e = r["_enr"]
                ax = r["arx_rank"] if r.get("arx_kind") == "real" else ""
                ox = r["oa_rank"] if r.get("oa_kind") == "real" else ""
                zx = r["zb_rank"] if r.get("zb_kind") == "real" else ""
                h = hindex.get(r["name"])
                h_val = h["h"] if h else ""
                h_src = h["source"] if h else ""
                w.writerow([r["display_rank"], r["name"], ascii_name(r["name"]),
                            r["institution"], r["country"], ax, ox, zx,
                            r.get("arx_papers", ""), r.get("oa_works", ""),
                            r.get("oa_cites", ""), r.get("zb_papers", ""),
                            h_val, h_src,
                            r["first_year"], r["last_year"],
                            e.get("birth_year", ""), e.get("advisor", ""),
                            e.get("orcid", ""), e.get("qid", "")])
    n_wd = sum(1 for r in living if r["_enr"].get("qid"))
    body = f"""<h1>Data and citation</h1>
<p class="subtitle">The wwigr.org Top 100 as an open dataset</p>

<p>The ranked list behind this site is available as a single CSV file under a <a href="https://creativecommons.org/licenses/by/4.0/">Creative Commons Attribution 4.0</a> licence. You are free to reuse it, including for commercial work, as long as you give credit.</p>

<p class="callout"><a href="data/wwigr_top100.csv"><strong>Download wwigr_top100.csv</strong></a> &nbsp; {len(living)} researchers, {n_wd} of them matched to Wikidata.</p>

<h2>What is in the file</h2>
<p>One row per researcher, in rank order. The columns are: rank, name (with diacritics), name_ascii (plain ASCII for spreadsheet compatibility), institution, country, the arXiv, OpenAlex, and zbMATH composite ranks, arXiv paper count, OpenAlex work and citation counts, overall h-index (Scholar or OpenAlex, whichever is higher), first and last active year, and, for the researchers matched to Wikidata, birth year, doctoral advisor, ORCID, and Wikidata identifier. A pipeline rank is left blank when the researcher did not appear in that pipeline; the overall ranking used an interpolated estimate in its place (see <a href="methodology.html">Methodology</a>).</p>

<h2>How to cite</h2>
<blockquote>Hubbard, S. (2026). Who's Who in Goldbach Research. Zenodo. <a href="{DOI_URL}">{DOI_URL}</a></blockquote>
<p>The DOI <a href="{DOI_URL}">{DOI_CONCEPT}</a> always resolves to the current version. Every release is also archived on <a href="https://zenodo.org/records/20355376">Zenodo</a> with its own version DOI.</p>

<h2>How the ranking is built</h2>
<p>The full pipeline, arXiv preprint output, OpenAlex topical citations, zbMATH MSC classifications, and the Mathematics Genealogy Project combined into a composite score, is documented on the <a href="methodology.html">Methodology</a> page.</p>
"""
    _write("data.html", _page("Data and citation", body, "data.html"))


def write_sitemap_robots():
    if DRY:
        return
    today = datetime.date.today().isoformat()
    urls = []
    for path in sorted(SITE.rglob("*.html")):
        rel = str(path.relative_to(SITE)).replace("\\", "/")
        urls.append(BASE + "/" if rel == "index.html" else BASE + "/" + rel[:-5])
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>")
    sm.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: https://wwigr.org/sitemap.xml\n",
        encoding="utf-8")
    print(f"  sitemap.xml ({len(urls)} urls), robots.txt")


def main():
    print("publish.py" + (" (dry run)" if DRY else ""))
    pool = load_pool()
    oa_by_name, oa_by_surname = load_oa_ids()
    homepages = load_homepages()
    scholar = load_scholar()
    hindex = load_hindex()
    zbmath = load_zbmath()
    gen_people = load_genealogy()
    enr = load_enrichment()
    pool.sort(key=lambda r: int(r["merged_rank"]))
    living = [r for r in pool if r["status"] != "deceased"]
    deceased = [r for r in pool if r["status"] == "deceased"]
    top100 = living[:100]
    seen = {}
    for i, r in enumerate(top100, start=1):
        r["display_rank"] = i
        s = slugify(r["name"])
        seen[s] = seen.get(s, 0) + 1
        r["slug"] = s if seen[s] == 1 else f"{s}-{seen[s]}"
    print(f"  pool {len(pool)}, living {len(living)}, deceased {len(deceased)}")
    other_set = ({r["country"] for r in top100 if r["country"] not in ("", "NA")}
                 - NA_COUNTRIES - EU_COUNTRIES - AS_COUNTRIES)
    other_rows = [r for r in top100 if r["country"] in other_set]
    if other_rows:
        NAV_ITEMS.insert(5, ("regions/other.html", "Other regions"))
    render_index(top100, bool(other_rows))
    render_top100(top100, hindex)
    render_region(top100, "north-america", "North America", NA_COUNTRIES,
                  "11_top100_north_america.png",
                  "Top 100 researchers are based in North America.")
    render_region(top100, "europe", "Europe", EU_COUNTRIES,
                  "12_top100_europe.png",
                  "Top 100 researchers are based in Europe.")
    render_region(top100, "asia", "Asia and the Pacific",
                  AS_COUNTRIES, "13_top100_asia.png",
                  "Top 100 researchers are based in Asia or the Pacific.")
    # Catch-all region: only rendered when someone actually lands outside
    # the three named regions. Left out entirely when empty.
    if other_rows:
        render_region(top100, "other", "Other regions", other_set,
                      "14_top100_other.png",
                      "Top 100 researchers are based outside the three "
                      "named regions.")
    top_slugs = {r["slug"] for r in top100}
    used_slugs = set(top_slugs)
    ADV_SLUG.clear()
    for _p in top100:
        ADV_SLUG[slugify(_p["name"])] = _p["slug"]
    for _p in gen_people:
        ADV_SLUG.setdefault(slugify(_p["name"]), _p["slug"])
    render_inmemoriam(deceased, oa_by_name, oa_by_surname, homepages,
                      scholar, hindex, zbmath, used_slugs)
    render_reading_list()
    render_data(top100, enr, hindex)
    render_profiles(top100, oa_by_name, oa_by_surname, homepages, scholar, hindex, zbmath)
    render_genealogy_profiles(gen_people, top_slugs, oa_by_name,
                              oa_by_surname, homepages, scholar, hindex,
                              zbmath, used_slugs)
    render_acknowledged(oa_by_name, oa_by_surname, homepages, scholar, hindex, zbmath)
    write_sitemap_robots()
    print("done. static pages (genealogy, about, methodology) left untouched.")


if __name__ == "__main__":
    main()
