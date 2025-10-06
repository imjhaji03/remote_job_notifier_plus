# Remote Job Notifier — EU Remote Java/Spring (ATS + Email Alerts)

This project emails you a **daily digest** of remote Java/Spring Boot jobs that are **Europe/EMEA-friendly**.  
It pulls from **ATS job-board APIs** (safe + ToS-compliant) and can **optionally merge your Gmail job alerts**
(LinkedIn / Indeed / Naukri / Internshala) from a specific label — without scraping those sites.

## Sources (two safe tracks)

### 1) ATS job-board APIs (pull data directly)
- **Greenhouse** Job Board API (`boards-api.greenhouse.io`)
- **Lever** Postings API (`api.lever.co`)
- **Ashby** Public Job Posting API (`api.ashbyhq.com`)
- (Also supported from the previous version) **Remotive**, **RemoteOK**, **Adzuna**

> These endpoints are designed for public job-board consumption. You add the companies you care about in `sources.json`.

### 2) Gmail Job Alerts (merge links, no scraping)
- Create job alerts on **LinkedIn**, **Indeed**, **Naukri**, **Internshala** for your keywords.
- Auto-label those emails in Gmail (e.g., label: `job-alerts`).
- This tool connects via **IMAP** (with an app password) and extracts links from the labeled messages in the last 24 hours to include in your digest.

> This respects platform ToS: we ingest **your** emails, not their websites.

---

## Quick Start (GitHub Actions)

1. **Create a new private repo** and upload this project.
2. Add **Actions secrets** (Settings → Secrets and variables → Actions):
   - `SMTP_HOST`, `SMTP_PORT` (e.g., 587), `SMTP_USER`, `SMTP_PASS`
   - `EMAIL_FROM`, `EMAIL_TO`
   - *(Optional)* `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`
   - *(Optional)* IMAP for Gmail alerts:  
     - `IMAP_HOST=imap.gmail.com`, `IMAP_PORT=993`, `IMAP_USER`, `IMAP_PASS`, `IMAP_LABEL=job-alerts`
3. Edit `sources.json` with companies you want to watch (Greenhouse `board_token`, Lever `company`, Ashby `job_board_name`). Examples included.
4. Commit & push. Actions will run daily at **08:00 IST** and email your digest.

### Local Run
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER="your_user"
export SMTP_PASS="your_app_password"
export EMAIL_FROM="you@example.com"
export EMAIL_TO="you@example.com"

# Optional: IMAP (Gmail alerts)
export IMAP_HOST=imap.gmail.com
export IMAP_PORT=993
export IMAP_USER="you@gmail.com"
export IMAP_PASS="your_gmail_app_password"
export IMAP_LABEL="job-alerts"

python job_notifier.py
```

---

## Configure keywords and geographies

- `config.json` → control matching:
  - `keywords` and `extra_keywords_any`
  - `regions_any` (Europe/EMEA/countries)
  - `countries_iso2` (used for Adzuna + insights bucketing)
  - `send_if_empty`

- `sources.json` → list ATS sources to poll:
```json
{
  "greenhouse": ["datadog", "snowflake", "elastic", "okta"],
  "lever": ["duolingo", "ramp", "checkoutcom"],
  "ashby": ["stripe", "figma", "linear"]
}
```

> Find the tokens:  
> - Greenhouse: `https://boards.greenhouse.io/<board_token>`  
> - Lever: `https://api.lever.co/v0/postings/<company>?mode=json`  
> - Ashby: `https://jobs.ashbyhq.com/<job_board_name>`

---

## Daily Email
- **New matches first** (de-duplicated), then **“Gmail Alerts” links** (if enabled)
- **Insights**: top recurring skills in today’s matches, country buckets, source counts

---

## Notes / ToS
- **LinkedIn/Indeed/Naukri/Internshala**: scraping is prohibited by their ToS; use email alerts instead.  
- **Greenhouse/Lever/Ashby**: public job-board endpoints intended for consumption.  
- **RemoteOK/Remotive**: remember to **credit + link** back when using data.
#
