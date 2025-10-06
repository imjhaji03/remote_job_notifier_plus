import os, json, re, ssl, smtplib, time, hashlib, tldextract, math
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timezone
from urllib.parse import quote_plus
import requests

# providers
from providers import greenhouse, lever, ashby, imap_ingest

CONFIG_PATH = "config.json"
SOURCES_PATH = "sources.json"
STATE_PATH = "state/jobs_seen.json"

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def mk_id(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]

def matches_filters(job, cfg):
    title = (job.get("title") or "") + " " + (job.get("tags") or "")
    text = (job.get("description") or "")
    where = (job.get("location") or "") + " " + (job.get("region") or "") + " " + (job.get("candidate_required_location") or "")
    blob = " ".join([title, text]).lower()
    if not any(k.lower() in blob for k in cfg["keywords"]):
        return False
    where_l = where.lower()
    if cfg["regions_any"]:
        if not any(r.lower() in where_l for r in cfg["regions_any"]):
            if not any(r.lower() in blob for r in cfg["regions_any"]):
                return False
    return True

def normalize(j):
    url = j.get("url") or ""
    j["id"] = mk_id(f"{j.get('source')}|{j.get('company')}|{j.get('title')}|{url}")
    return j

def collect_ats(cfg, sources):
    jobs = []
    for token in sources.get("greenhouse", []):
        try: jobs += greenhouse.fetch(token, content=True)
        except Exception as e: print("Greenhouse error", token, e)
    for comp in sources.get("lever", []):
        try: jobs += lever.fetch(comp)
        except Exception as e: print("Lever error", comp, e)
    for board in sources.get("ashby", []):
        try: jobs += ashby.fetch(board, include_comp=False)
        except Exception as e: print("Ashby error", board, e)
    filt = [normalize(j) for j in jobs if matches_filters(j, cfg) and len((j.get('description') or '')) >= cfg.get("min_desc_len", 10)]
    return filt

def collect_feeds(cfg):
    jobs = []
    # Remotive
    try:
        url = f"https://remotive.com/api/remote-jobs?search={quote_plus('java spring boot')}&limit={int(cfg.get('max_results_per_source',200))}"
        r = requests.get(url, timeout=30); r.raise_for_status()
        for x in r.json().get("jobs", []):
            jobs.append({
                "source": "remotive",
                "title": x.get("title"),
                "company": x.get("company_name"),
                "location": x.get("candidate_required_location") or "",
                "candidate_required_location": x.get("candidate_required_location") or "",
                "tags": " ".join(x.get("tags", []) or []),
                "description": x.get("description") or "",
                "url": x.get("url"),
                "region": "",
                "posted_at": x.get("publication_date"),
            })
    except Exception as e:
        print("Remotive error:", e)

    # RemoteOK
    try:
        r = requests.get("https://remoteok.io/api", timeout=30, headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"}); r.raise_for_status()
        for x in r.json():
            if not isinstance(x, dict): continue
            pos = x.get("position") or x.get("title"); 
            if not pos: continue
            jobs.append({
                "source": "remoteok",
                "title": pos,
                "company": x.get("company") or "",
                "location": x.get("location") or "",
                "candidate_required_location": x.get("location") or "",
                "tags": " ".join(x.get("tags", []) or []),
                "description": x.get("description") or "",
                "url": x.get("url") or x.get("apply_url"),
                "region": "",
                "posted_at": x.get("date") or x.get("epoch"),
            })
    except Exception as e:
        print("RemoteOK error:", e)

    # Adzuna (EU countries)
    try:
        app_id = os.environ.get("ADZUNA_APP_ID"); app_key = os.environ.get("ADZUNA_APP_KEY")
        if app_id and app_key:
            for c in ["fr","ie","de","nl","be","es","it","pt","se","no","dk","fi","at","ch","gb"]:
                url = f"https://api.adzuna.com/v1/api/jobs/{c}/search/1?app_id={app_id}&app_key={app_key}&what={quote_plus('Java Spring Boot remote')}&results_per_page=50"
                r = requests.get(url, timeout=30); 
                if r.status_code != 200: continue
                for x in r.json().get("results", []):
                    jobs.append({
                        "source": f"adzuna_{c}",
                        "title": x.get("title"),
                        "company": (x.get("company") or {}).get("display_name",""),
                        "location": ((x.get("location") or {}).get("display_name")) or "",
                        "candidate_required_location": ((x.get("location") or {}).get("display_name")) or "",
                        "tags": "",
                        "description": x.get("description") or "",
                        "url": x.get("redirect_url"),
                        "region": "",
                        "posted_at": x.get("created"),
                    })
    except Exception as e:
        print("Adzuna error:", e)

    return [normalize(j) for j in jobs if matches_filters(j, cfg)]

def render_insights(jobs, cfg):
    if not jobs: return ""
    from collections import Counter
    blob = " ".join([(j.get("title") or "") + " " + (j.get("description") or "") + " " + (j.get("tags") or "") for j in jobs]).lower()
    skills = cfg["keywords"] + cfg.get("extra_keywords_any", [])
    hits = Counter()
    for s in skills:
        if s.lower() in blob:
            hits[s.lower()] += blob.count(s.lower())
    top = hits.most_common(8)
    countries = Counter()
    for j in jobs:
        where = " ".join([j.get("location") or "", j.get("candidate_required_location") or ""]).lower()
        for name in ["france","ireland","germany","netherlands","belgium","spain","italy","portugal","sweden","norway","denmark","finland","austria","switzerland","united kingdom","uk","europe","emea"]:
            if name in where: countries[name] += 1
    skill_html = "".join([f"<li>{k} — {v}</li>" for k,v in top]) or "<li>No dominant skills today</li>"
    country_html = "".join([f"<li>{k.title()} — {v}</li>" for k,v in countries.most_common()]) or "<li>None detected</li>"
    return f"""
    <h3 style='margin:16px 0 6px 0;'>Insights</h3>
    <ul>{skill_html}</ul>
    <h4 style='margin:10px 0 6px 0;'>Locations Mentioned</h4>
    <ul>{country_html}</ul>
    """

def send_email(html, cfg):
    host = os.environ.get("SMTP_HOST"); port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER"); pw = os.environ.get("SMTP_PASS")
    sender = os.environ.get("EMAIL_FROM"); to = os.environ.get("EMAIL_TO")
    if not all([host, port, user, pw, sender, to]):
        print("Missing SMTP or EMAIL_* env vars; skipping email.")
        return False
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = cfg.get("email_subject", "Daily Remote Jobs Digest")
    msg["From"] = sender; msg["To"] = to; msg["Date"] = formatdate(localtime=True)
    import ssl, smtplib
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=ctx)
        server.login(user, pw)
        server.sendmail(sender, [to], msg.as_string())
    return True

def render_email(jobs_new, links, cfg):
    rows = []
    for j in jobs_new:
        rows.append(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <div style="font-size:15px;font-weight:600;">
              <a href="{j.get('url')}" target="_blank" rel="noopener noreferrer">{j.get('title')}</a>
            </div>
            <div style="font-size:13px;color:#444;">{(j.get('company') or '').strip()} · {(j.get('location') or j.get('candidate_required_location') or 'Remote')}</div>
            <div style="font-size:12px;color:#666;margin-top:6px;">Source: {j.get('source')}</div>
          </td>
        </tr>
        """)
    table = "<table cellspacing='0' cellpadding='0' width='100%'>" + "\n".join(rows) + "</table>" if rows else "<p>No new ATS/feed matches today.</p>"
    links_html = ""
    if links:
        linklis = "".join([f"<li><a href='{u}' target='_blank' rel='noopener'>{u}</a></li>" for u in links])
        links_html = f"<h3 style='margin:16px 0 6px 0;'>Links from Email Alerts</h3><ul>{linklis}</ul>"
    header = f"<h2 style='margin:0 0 10px 0;'>EU-Remote Java/Spring Jobs — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</h2>"
    insights = render_insights(jobs_new, cfg)
    footer = "<div style='font-size:12px;color:#888;margin-top:12px;'>This digest links to original postings (Greenhouse/Lever/Ashby/Remotive/RemoteOK/Adzuna) and your email alerts.</div>"
    return header + table + links_html + insights + footer

def main():
    cfg = load_json(CONFIG_PATH, {})
    src = load_json(SOURCES_PATH, {"greenhouse":[], "lever":[], "ashby":[]})
    seen = set(load_json(STATE_PATH, {"ids": []}).get("ids", []))

    ats_jobs = collect_ats(cfg, src)
    feed_jobs = collect_feeds(cfg)
    all_jobs = ats_jobs + feed_jobs
    new_jobs = [j for j in all_jobs if j["id"] not in seen]

    links = []
    if os.environ.get("IMAP_HOST") and os.environ.get("IMAP_USER") and os.environ.get("IMAP_PASS") and os.environ.get("IMAP_LABEL"):
        try:
            links = imap_ingest.fetch_links_from_label(
                os.environ["IMAP_HOST"],
                int(os.environ.get("IMAP_PORT","993")),
                os.environ["IMAP_USER"],
                os.environ["IMAP_PASS"],
                os.environ["IMAP_LABEL"],
                days=1
            )
        except Exception as e:
            print("IMAP ingestion failed:", e)
            links = []

    html = render_email(new_jobs, links, cfg)
    sent = send_email(html, cfg)
    print("Sent:", sent, "New jobs:", len(new_jobs), "Links:", len(links))

    for j in all_jobs: seen.add(j["id"])
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(list(seen))}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
