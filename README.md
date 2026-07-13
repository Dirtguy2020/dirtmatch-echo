# ECHO Weekly Preprocessor — the ~35-state lead unlock

EPA's ECHO bulk file contains every state's construction stormwater permit coverages
(the TXR150 equivalents nationwide) with **operator names** — roughly 1,500–2,500 fresh
NOIs/month beyond what the n8n workflow already pulls. The file is 330 MB zipped / 2.2 GB
unzipped, too big for n8n cloud, so a free GitHub Action does the heavy lifting weekly and
hands n8n a small CSV.

## Setup (one time, ~5 minutes)

1. Create a GitHub repo (private is fine), e.g. `dirtmatch-echo`.
2. Add `filter_echo.py` (from this folder) to the repo root.
3. Add `echo-weekly.yml` (from this folder) at the path `.github/workflows/echo-weekly.yml`.
4. In the repo: Settings → Actions → General → Workflow permissions → enable
   **Read and write permissions** (so the Action can commit the CSV).
5. Run it once manually: Actions tab → "ECHO weekly lead extract" → Run workflow.
   It takes ~10–20 minutes and commits `echo_leads.csv` to the repo.
6. If the repo is **private**, n8n needs a GitHub token to fetch the raw file
   (fine-grained PAT with Contents:Read on this repo). If **public**, no token needed.

## Then tell Claude the repo URL

The n8n branch is one Fetch → Parse CSV → Cap → Merge chain pointing at:
`https://raw.githubusercontent.com/<you>/<repo>/main/echo_leads.csv`
Claude can wire it into the main workflow in one edit — the CSV already matches the
pipeline's canonical lead schema (contractor_raw, address, city, state, etc.), so no
normalization is needed and Apollo/SerpAPI enrichment picks these leads up automatically.

## Notes

- `SKIP_STATES` in the script excludes states the workflow already covers directly
  (TX, UT, IL, SD, and the EPA NeT states) so nothing is double-contacted.
  NC is intentionally NOT skipped — its leads come through this file (an in-n8n
  NC spreadsheet branch was tried and crashed n8n cloud's memory limit).
- Known-dead states in ECHO (no fresh data flows regardless): GA (since Aug 2023),
  NV (since 2015), CA and VA (own systems). Those need separate handling later.
- `LOOKBACK_DAYS=10` gives overlap between weekly runs; the n8n dedup layers
  handle any repeats.
