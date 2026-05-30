# wwigr.org

Source for the Who's Who in Goldbach Research site at https://wwigr.org.

## Layout

- `_site/` is the deployable static site (HTML, CSS, images). Cloudflare deploys this directory.
- `*.qmd` files are Quarto sources (used when you re-render with Quarto).
- `data_overrides.csv` patches upstream data (e.g., institution corrections) that are wrong in the source CSVs.
- `wrangler.toml` tells Cloudflare to serve `_site/` as static assets.

## Deployment

This repo is connected to Cloudflare Workers Builds. Every push to `main` triggers an auto-deploy to https://wwigr.org. No manual upload needed.

## Updating the site

Two flavors of update.

### Website-only changes (text, layout, styling)

Edit the HTML in `_site/` directly. Commit. Push. Cloudflare auto-deploys in 30-45s. For changes that touch many pages or are higher-risk, push to a non-`main` branch first and review the preview URL Cloudflare assigns; merge to `main` when satisfied.

### Data refresh (after a new R pipeline run)

Run `python publish.py` from this folder. It reads the latest CSVs from `../out/`, `../out-mg/`, `../out-oa/`, applies `data_overrides.csv`, and rewrites `_site/top100.html`, `_site/regions/*.html`, `_site/genealogy.html`, `_site/reading-list.html`, `_site/index.html`, plus the four region-map PNGs in `_site/img/`. Then commit and push as above.

Use `python publish.py --check` for a dry run (reports what would change without writing).

`data_overrides.csv` is the place to fix institution or country values that are wrong upstream and would otherwise reappear on every re-run.

### Preview branches

Cloudflare Workers Builds redeploys `main` to https://wwigr.org and any other branch to a unique URL like `preview-<hash>.wwigr.sthubbar.workers.dev`. Push risky changes to `preview` first, eyeball, then merge to `main`.
