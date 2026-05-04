# wwigr.org deployment guide

This folder is a Quarto project that builds the wwigr.org website from the
Goldbach research data. The pipeline:

```
data CSVs in ../out/  ->  quarto render  ->  _site/ (HTML)  ->  Cloudflare Pages  ->  wwigr.org
```

Total cost: about $11/year for the domain. Hosting is free.

## One-time setup

### 1. Install Quarto (once, free, ~5 minutes)

Download from <https://quarto.org/docs/get-started/>. Pick the Windows
installer. After install, open a fresh PowerShell or Command Prompt and run

```
quarto --version
```

You should see something like `1.5.x`. If R was already on your PATH (it
is), Quarto will auto-detect it.

### 2. Install R packages used by the site (once, free, ~2 minutes)

In RStudio, run:

```r
install.packages(c("DT", "knitr"))
```

These are used to render the sortable HTML tables.

## Build the site

Open a terminal in this folder (`Project/website/`) and run:

```
quarto render
```

Output goes to `_site/`. Open `_site/index.html` in any browser to preview.
Each render takes 10-30 seconds.

To preview while editing, run

```
quarto preview
```

It opens a live browser tab that auto-reloads on save.

## Deploy to Cloudflare Pages (free)

### Step 1. Create a Cloudflare account (once)

Sign up at <https://dash.cloudflare.com/sign-up>. Free tier covers everything
this site needs.

### Step 2. Create a Pages project

1. In the Cloudflare dashboard, go to **Workers & Pages** in the sidebar.
2. Click **Create application** -> **Pages** -> **Upload assets**.
3. Project name: `wwigr` (this becomes `wwigr.pages.dev` until DNS is set).
4. Drag the `_site/` folder from this directory onto the upload zone.
5. Click **Deploy site**.

After about 30 seconds you'll have a live URL like
`https://wwigr.pages.dev` showing the site.

To deploy updates: zip the `_site/` folder and re-upload, OR connect to a
GitHub repo for auto-deploy on push (later).

## Buy and connect the wwigr.org domain

### Step 3. Buy the domain at Cloudflare Registrar

Cloudflare Registrar sells at-cost: about $11/year for `.org`. No markup, no
upsells. Available at
<https://dash.cloudflare.com/?to=/:account/registrar>.

Search for `wwigr.org`, add to cart, check out. Steve enters his credit
card. Auto-renewal is on by default.

### Step 4. Connect the domain to the Pages project

In the same Cloudflare Pages project from Step 2:

1. Open the project settings.
2. **Custom domains** -> **Set up a domain**.
3. Type `wwigr.org` and confirm. Cloudflare auto-detects it's registered
   under the same account and adds the DNS records.
4. Wait 5-10 minutes for DNS propagation.

The site is now live at <https://wwigr.org>. HTTPS certificate is automatic
via Cloudflare. WWW redirect (`www.wwigr.org` -> `wwigr.org`) is also
handled.

## Updating the site

When the underlying data changes:

1. Re-run the upstream R scripts (gb_merge, gb_render_listings, etc.)
   to refresh the CSVs and PNGs in `../out/` and `../out-mg/` and
   `../out-oa/`.
2. From this folder, run `quarto render`.
3. Re-upload the `_site/` folder to Cloudflare Pages.

A future improvement: connect the GitHub repo to Cloudflare Pages so that
git pushes auto-trigger a rebuild and redeploy.

## Files in this directory

```
_quarto.yml             site config (nav bar, theme)
styles.css              custom CSS (academic look, tier colors)
index.qmd               home page
top100.qmd              the canonical Top 100 list
regions/
  north-america.qmd
  europe.qmd
  asia.qmd
genealogy.qmd           MGP-based close relations
reading-list.qmd        2,000+ short Goldbach papers
methodology.qmd         how the rankings are built
about.qmd               who, why, citation
DEPLOY.md               this file
```
