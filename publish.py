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
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"
UP = ROOT.parent
BASE = "https://wwigr.org"
SITE_NAME = "Who's Who in Goldbach Research"
SITE_DESC = ("A directory of the researchers most active on the Goldbach "
             "conjecture, ranked from arXiv preprint output and OpenAlex "
             "citation data.")
DOI_CONCEPT = "10.5281/zenodo.20355375"
DOI_URL = "https://doi.org/" + DOI_CONCEPT
VERIFY_TAG = ('<meta name="google-site-verification" '
              'content="nTo_CIJXODwXPNsVkC0oT7IYWnRXP3F8U4344Z_ylMs" />')

NA_COUNTRIES = {"US", "CA", "MX"}
EU_COUNTRIES = {
    "AD","AL","AT","BA","BE","BG","BY","CH","CY","CZ","DE","DK","EE","ES",
    "FI","FO","FR","GB","GR","HR","HU","IE","IS","IT","LI","LT","LU","LV",
    "MC","MD","ME","MK","MT","NL","NO","PL","PT","RO","RS","RU","SE","SI",
    "SK","SM","UA","VA","XK","TR","IL",
}
AS_COUNTRIES = {
    "AE","AF","AM","AU","AZ","BD","BH","BN","BT","CN","GE","HK","ID","IN",
    "IQ","IR","JO","JP","KG","KH","KP","KR","KW","KZ","LA","LB","LK","MM",
    "MN","MO","MV","MY","NP","NZ","OM","PG","PH","PK","PS","QA","SA","SG",
    "SY","TH","TJ","TL","TM","TW","UZ","VN","YE","FJ",
}

DRY = "--check" in sys.argv

NAV_ITEMS = [
    ("index.html",                  "Home"),
    ("top100.html",                 "Top 100"),
    ("regions/north-america.html",  "North America"),
    ("regions/europe.html",         "Europe"),
    ("regions/asia.html",           "Asia"),
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
<p>Maintained by Steve Hubbard (<a href="mailto:admin@wwigr.org">admin@wwigr.org</a>). Data sources: <a href="https://arxiv.org">arXiv</a>, <a href="https://openalex.org">OpenAlex</a>, <a href="https://www.mathgenealogy.org">Mathematics Genealogy Project</a>.</p>
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
    return enr


def load_overrides():
    ov = {}
    path = ROOT / "data_overrides.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for o in csv.DictReader(f):
                ov[o["name"]] = {k: o[k].strip() for k in
                                 ("institution", "country", "birth_date", "death_date")
                                 if (o.get(k) or "").strip()}
    return ov


def load_oa_ids():
    ids = {}
    matches = sorted(glob.glob(str(UP / "out-oa/gb_oa_master_*.csv")))
    if matches:
        with open(matches[-1], encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ids[r["author_name"]] = r["author_id"].rsplit("/", 1)[-1]
    return ids


def load_homepages():
    hp = {}
    path = ROOT / "homepages.csv"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("url") or "").strip():
                    hp[r["name"]] = r["url"].strip()
    return hp


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
        if "institution" in o:
            r["institution"] = o["institution"]
        if "country" in o:
            r["country"] = o["country"]
        e = enr.get(r["name"], {})
        r["_enr"] = e
        death = o.get("death_date") or e.get("death_date") or ""
        birth = o.get("birth_date") or e.get("birth_year") or ""
        r["death_date"] = death
        r["birth_date"] = birth
        r["status"] = "deceased" if death else "living"
    return rows


def render_top100(rows):
    body_rows = []
    for r in sorted(rows, key=lambda r: r["display_rank"]):
        ax = "-" if r["arx_rank"] == "156" else r["arx_rank"]
        ox = "-" if r["oa_rank"] == "1114" else r["oa_rank"]
        name = f'<a href="people/{r["slug"]}.html">{esc(r["name"])}</a>'
        body_rows.append(
            f"<tr><td>{r['display_rank']}</td><td>{name}</td>"
            f"<td>{esc(r['institution'])}</td><td>{esc(r['country'])}</td>"
            f"<td>{ax}</td><td>{ox}</td><td>{esc(r['provenance'])}</td>"
            f"<td>{r['first_year']}</td><td>{r['last_year']}</td></tr>")
    prov = Counter(r["provenance"] for r in rows)
    prov_rows = "".join(
        f"<tr><td><code>{esc(k)}</code></td><td style='text-align:right'>{v}</td></tr>"
        for k, v in prov.most_common())
    body = f"""<h1>The Top 100</h1>
<p class="subtitle">Researchers active on Goldbach and adjacent problems</p>

<p>The list is sortable on any column. Type in the search box to filter by name, institution, or country. Click any name for that researcher's profile page.</p>

<p>This page shows the 100 highest-ranked living researchers, renumbered 1 to 100. Researchers in the ranked pool who have passed away are remembered on the <a href="in-memoriam.html">In Memoriam</a> page.</p>

<p class="callout"><strong>Reading the columns.</strong> <em>arXiv rank</em> and <em>OA rank</em> are the researcher's position in the full composite score for each pipeline (arXiv composite = 60% papers + 40% eigenvector centrality, out of 155 qualifying authors; OA composite = 60% topical papers + 40% topical citations, out of 1,113 OA authors). Lower is better. A dash means the researcher did not qualify in that pipeline.</p>

<table id="top100tbl" class="display compact stripe hover" style="width:100%">
<thead><tr><th>Rank</th><th>Name</th><th>Institution</th><th>Country</th><th>arXiv rank</th><th>OA rank</th><th>Source</th><th>First year</th><th>Last year</th></tr></thead>
<tbody>
{chr(10).join(body_rows)}
</tbody>
</table>
<script>
$(document).ready(function() {{
  $('#top100tbl').DataTable({{ pageLength: 25, lengthMenu: [25, 50, 100], order: [[0, 'asc']] }});
}});
</script>

<h2>Provenance breakdown</h2>
<ul>
<li><code>both</code>: in arXiv 155 AND OpenAlex top pool. The unanimous core.</li>
<li><code>oa_only</code>: discovered by OpenAlex but not arXiv-active. These are senior figures who publish in journals and don't post preprints.</li>
<li><code>arxiv_only</code>: present only if at least one arXiv-only entry made the sum_rank cutoff.</li>
<li><code>manual_add</code>: manually inserted via <code>gb_manual_additions.csv</code>.</li>
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
    body = f"""<h1>{esc(title)}</h1>
<p class="subtitle">Top 100 researchers based in {esc(title)}</p>

<p>{len(rs)} {blurb}</p>

<div class="figure-page">
<img src="../img/{png}" alt="Map of {esc(title)} Top 100 researchers">
</div>

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


def render_inmemoriam(deceased):
    rows = sorted(deceased, key=lambda r: r.get("death_date") or "")

    def years(r):
        b = (r.get("birth_date") or "")[:4]
        d = (r.get("death_date") or "")[:4]
        return f"{b}-{d}" if b and d else (f"d. {d}" if d else "")

    body_rows = "\n".join(
        f"<tr><td>{esc(r['name'])}</td><td>{esc(r['institution'])}</td>"
        f"<td>{esc(r['country'])}</td><td>{years(r)}</td></tr>"
        for r in rows)
    body = f"""<h1>In Memoriam</h1>
<p class="subtitle">Researchers in this directory who are no longer with us</p>

<p>The Top 100 and the regional pages list living researchers only, so the directory stays accurate for anyone using it to make contact. This page remembers the {len(rows)} researchers in the ranked pool who have passed away. Several of them, including G. H. Hardy and J. E. Littlewood, are foundational figures whose methods modern Goldbach research still builds on.</p>

<table class="display compact stripe" style="width:100%">
<thead><tr><th>Name</th><th>Institution</th><th>Country</th><th>Years</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>

<p class="callout">A researcher missing here, or listed here in error? Email <a href="mailto:admin@wwigr.org">admin@wwigr.org</a> and it will be corrected.</p>
"""
    _write("in-memoriam.html", _page("In Memoriam", body, "in-memoriam.html"))


def render_profiles(people, oa_ids, homepages):
    for r in people:
        e = r.get("_enr", {})
        meta = []

        def add(label, val):
            if val not in (None, "", "NA"):
                meta.append(f"<tr><td>{label}</td><td>{val}</td></tr>")

        add("Rank on the Top 100", f"#{r['display_rank']}")
        add("Institution", esc(r["institution"]))
        add("Country", esc(r["country"]))
        add("Born", (r.get("birth_date") or "")[:4])
        add("Doctoral advisor", esc(e.get("advisor") or ""))
        add("arXiv Goldbach-topical papers", r.get("arx_papers"))
        add("OpenAlex topical works", r.get("oa_works"))
        add("OpenAlex topical citations", r.get("oa_cites"))
        add("Active years", f"{r['first_year']} to {r['last_year']}")
        orcid = e.get("orcid") or ""
        if orcid:
            add("ORCID", f'<a href="https://orcid.org/{orcid}" target="_blank" rel="noopener">{orcid}</a>')

        links = []
        hp = homepages.get(r["name"])
        if hp:
            links.append(f'<a href="{esc(hp)}" target="_blank" rel="noopener">Homepage</a>')
        oaid = oa_ids.get(r["name"])
        if oaid:
            links.append(f'<a href="https://openalex.org/{oaid}" target="_blank" rel="noopener">Publication record on OpenAlex</a>')
        links_html = ("<p>" + " &middot; ".join(links) + "</p>") if links else ""

        body = f"""<p class="subtitle"><a href="../top100.html">&larr; Back to the Top 100</a></p>
<h1>{esc(r['name'])}</h1>
<p class="subtitle">{esc(r['institution'])} ({esc(r['country'])})</p>

<p>Number {r['display_rank']} on the wwigr.org Top 100 of researchers active on the Goldbach conjecture and adjacent problems in additive prime number theory.</p>

<table class="profile-table">
<tbody>
{chr(10).join(meta)}
</tbody>
</table>
{links_html}
<p class="callout">Profile data is compiled from arXiv, OpenAlex, and Wikidata, and the homepage link from a web search. Spotted an error or an omission? Email <a href="mailto:admin@wwigr.org">admin@wwigr.org</a>.</p>
"""
        rel = f"people/{r['slug']}.html"
        _write(rel, _page(r["name"], body, rel, depth=1))
    print(f"  {len(people)} profile pages "
          f"({sum(1 for r in people if homepages.get(r['name']))} with a homepage link)")


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
        title_link = f'<a href="{esc(url)}" target="_blank" rel="noopener">{title}</a>' if url else title
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


def render_index(rows):
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
<p>Three independent signals are combined:</p>
<ol>
<li><strong>arXiv preprint output</strong> since 2003, filtered to math.NT and math.CO categories, matched against 17 Goldbach-relevant search terms.</li>
<li><strong>OpenAlex topical citations</strong> for the Goldbach phrases (<code>Goldbach conjecture</code>, <code>Goldbach problem</code>, <code>Goldbach's conjecture</code>).</li>
<li><strong>The Mathematics Genealogy Project</strong>, which provides advisor-student trees for the people identified in the first two steps.</li>
</ol>
<p>The final ranking is a sum of arXiv-rank and OpenAlex-rank. People who score well in both pipelines rise. Two known false positives are explicitly excluded; full audit trail is in <a href="methodology.html">methodology</a>.</p>

<h2>Top 100 at a glance</h2>
<p>100 researchers, drawn from {len(by_country)} countries.</p>

<table><thead><tr><th>Country</th><th>Top 100 researchers</th></tr></thead><tbody>{cc_rows}</tbody></table>

<div class="figure-page">
<img src="img/10_top100_overview.png" alt="World overview map of Top 100 Goldbach researchers">
</div>

<h2>Where to start</h2>
<ul>
<li><a href="top100.html"><strong>The Top 100</strong></a> is the canonical ranked list, sortable in your browser.</li>
<li>Regional listings: <a href="regions/north-america.html">North America</a>, <a href="regions/europe.html">Europe</a>, <a href="regions/asia.html">Asia</a>.</li>
<li><a href="reading-list.html"><strong>Reading list</strong></a>: 2,000+ short Goldbach papers from 2018 onward, with clickable links.</li>
<li><a href="data.html"><strong>Data</strong></a>: the ranked list as an open CC-BY dataset, with a citable DOI.</li>
<li><a href="methodology.html"><strong>Methodology</strong></a>: how the data is built, audit decisions, and limitations.</li>
</ul>

<h2>Citing this site</h2>
<blockquote>Hubbard, S. (2026). <em>Who's Who in Goldbach Research</em>. Zenodo. <a href="{DOI_URL}">{DOI_URL}</a></blockquote>
"""
    _write("index.html", _page(SITE_NAME, body, "index.html", extra_head=VERIFY_TAG))


def render_data(living, enr):
    SITE.joinpath("data").mkdir(parents=True, exist_ok=True)
    cols = ["rank", "name", "institution", "country", "arxiv_rank", "openalex_rank",
            "arxiv_papers", "openalex_works", "openalex_citations",
            "first_active_year", "last_active_year", "birth_year",
            "doctoral_advisor", "orcid", "wikidata_id"]
    if not DRY:
        with open(SITE / "data/wwigr_top100.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in living:
                e = r["_enr"]
                ax = "" if r["arx_rank"] == "156" else r["arx_rank"]
                ox = "" if r["oa_rank"] == "1114" else r["oa_rank"]
                w.writerow([r["display_rank"], r["name"], r["institution"], r["country"],
                            ax, ox, r.get("arx_papers", ""), r.get("oa_works", ""),
                            r.get("oa_cites", ""), r["first_year"], r["last_year"],
                            e.get("birth_year", ""), e.get("advisor", ""),
                            e.get("orcid", ""), e.get("qid", "")])
    n_wd = sum(1 for r in living if r["_enr"].get("qid"))
    body = f"""<h1>Data and citation</h1>
<p class="subtitle">The wwigr.org Top 100 as an open dataset</p>

<p>The ranked list behind this site is available as a single CSV file under a <a href="https://creativecommons.org/licenses/by/4.0/">Creative Commons Attribution 4.0</a> licence. You are free to reuse it, including for commercial work, as long as you give credit.</p>

<p class="callout"><a href="data/wwigr_top100.csv"><strong>Download wwigr_top100.csv</strong></a> &nbsp; {len(living)} researchers, {n_wd} of them matched to Wikidata.</p>

<h2>What is in the file</h2>
<p>One row per researcher, in rank order. The columns are: rank, name, institution, country, the arXiv and OpenAlex composite ranks, arXiv paper count, OpenAlex work and citation counts, first and last active year, and, for the researchers matched to Wikidata, birth year, doctoral advisor, ORCID, and Wikidata identifier.</p>

<h2>How to cite</h2>
<blockquote>Hubbard, S. (2026). Who's Who in Goldbach Research. Zenodo. <a href="{DOI_URL}">{DOI_URL}</a></blockquote>
<p>The DOI <a href="{DOI_URL}">{DOI_CONCEPT}</a> always resolves to the current version. Every release is also archived on <a href="https://zenodo.org/records/20355376">Zenodo</a> with its own version DOI.</p>

<h2>How the ranking is built</h2>
<p>The full pipeline, arXiv preprint output, OpenAlex topical citations, and the Mathematics Genealogy Project combined into a composite score, is documented on the <a href="methodology.html">Methodology</a> page.</p>
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
    oa_ids = load_oa_ids()
    homepages = load_homepages()
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
    render_index(top100)
    render_top100(top100)
    render_region(top100, "north-america", "North America", NA_COUNTRIES,
                  "11_top100_north_america.png",
                  "Top 100 researchers are based in North America.")
    render_region(top100, "europe", "Europe", EU_COUNTRIES,
                  "12_top100_europe.png",
                  "Top 100 researchers are based in Europe.")
    render_region(top100, "asia", "Asia", AS_COUNTRIES,
                  "13_top100_asia.png",
                  "Top 100 researchers are based in Asia and Oceania.")
    render_inmemoriam(deceased)
    render_reading_list()
    render_data(top100, enr)
    render_profiles(top100, oa_ids, homepages)
    write_sitemap_robots()
    print("done. static pages (genealogy, about, methodology) left untouched.")


if __name__ == "__main__":
    main()
