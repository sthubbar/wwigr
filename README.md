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

Edit `_site/*.html` (or the `.qmd` sources, then re-render). Commit. Push. Cloudflare ships the change in about 30 seconds.
