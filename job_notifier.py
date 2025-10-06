import os, json, re, ssl, smtplib, time, hashlib, math
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

# ---------- utilities ----------

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def mk_id(s): 
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]

# ---------- new filters (title + experience) ----------

def title_passes(title: str, cfg: dict) -> bool:
    t = (title or "").lower()
    must_any = [s.lower() for s in cfg.get("title_must_include_any", [])]
    if must_any and not any(m in t for m in must_any):
        return False
    exclude_any = [s.lower() for s in cfg.get("title_exclude_any", [])]
    if exclude_any and any(x in t for x in exclude_any):
        return False
    return True

_YEARS_RE = re.compile(r'(\d+)\s*\+?\s*(?:year|yr)s?', re.IGNORECASE)
_RANGE_RE = re.compile(r'(\d+)\s*[-–—]\s*(\d+)\s*(?:year|yr)s?', re.IGNORECASE)

def experience_ok(text: str, cfg: dict) -> bool:
    exp = cfg.get("experience_filter", {})
    if not exp or not exp.get("enabled"):
        return True
    max_allowed = int(exp.get("max_years_inclusive", 1))
    blob = (text or "").lower()

    # Positive markers: entry-level, junior, 0-1, graduate, etc.
    for m in exp.get("positive_markers_any", []):
        if m.lower() in blob:
            return True
    # Negative markers: 2+ years, senior, mid-level, etc.
    for m in exp.get("negative_markers_any", []):
        if m.lower() in blob:
            return False

    # Ranges like "0-1 years"
    r = _RANGE_RE.search(blob)
    if r:
        try:
            lo = int(r.group(1)); hi = int(r.group(2))
            return hi <= max_allowed
        except:
            pass

    # Singles like "1 year", "2+ years"
    hits = _YEARS_RE.findall(blob)
    if hits:
        try:
            nums = [int(h) for h in hits]
            # reject if any explicit year count exceeds max_allowed
            if any(n > max_allowed for n in nums):
                return False
            return True
        except:
            pass

    # If no explicit info, be permissive
    return True

# ---------- main filter pipeline ----------

def matches_filters(job, cfg):
    title = (job.get("title") or "")
    tags = (job.get("tags") or "")
    text = (job.get("description") or "")
    where = (job.get("location") or "") + " " + (job.get("region") or "") + " " + (job.get("candidate_required_location") or "")

    blob = " ".join([title, tags, text]).lower()

    # 1) Base skills/keywords (from config)
    base_keywords = cfg.get("keywords", [])
    if base_keywords and not any(k.lower() in blob for k in base_keywords):
        return False

    # 2) Geography (soft allow if mentioned anywhere)
    where_l = where.lower()
    regions_any = cfg.get("regions_any", [])
    if regions_any:
        if not any(r.lower() in where_l for r in regions_any) and not any(r.lower() in blob for r in regions_any):
            return False

    # 3) Title must/blacklist
    if not title_passes(title, cfg):
        return False

    # 4) Experience (0–1 yr filter if enabled)
    if not experience_ok(blob, cfg):
        return False

    return True

def normalize(j):
    url = j.get("url") or ""
    j["id"] = mk_id(f"{j.get('source')}|{j.get('company')}|{j.get('title')}|{url}")
    return j

# ---------- collectors ----------

def collect_ats(cfg, sources):
    jobs = []
    for token in sources.get("greenhouse", []):
        try:
            jobs += greenhouse.fetch(token, content=True)
        except Exception as e:
            print("Greenhouse error", token, e)
    for comp in sources.get("lever", []):
        try:
            jobs += lever.fetch(comp)
        except Exception as e:
            print("Lever error", comp, e)
    for board in sources.get("ashby", []):
        try:
            jobs += ashby.fetch(board, include_comp=False)
        except Exception as e:
            print("Ashby error", board, e)

    filt = [
        normalize(j) 
        for j in jobs 
        if matches_filters(j, cfg) and len((j.get('description') or '')) >= cfg.get("min_desc_len", 10)
    ]
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
        r = requests.get("https://remoteok.io/api", timeout=30, headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        for x in r.json():
            if not isinstance(x, dict):
                continue
            pos = x.get("position") or x.get("title")
            if not pos:
                continue
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
                r = requests.get(url, timeout=30)
                if r.status_code != 200:
                    continue
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

# ---------- insights & email ----------

def render_insights(jobs, cfg):
    if not jobs:
        return ""
    from collections import Counter
    blob = " ".join([(j.get("title") or "") + " " + (j.get("description") or "") + " " + (j.get("tags") or "") for j in jobs]).lower()
    skills = (cfg.get("keywords", []) or []) + (cfg.get("extra_keywords_any", []) or [])
    hits = Counter()
    for s in skills:
        sl = s.lower()
        if sl in blob:
            hits[sl] += blob.count(sl)
    top = hits.most_common(8)
    countries = Counter()
    for j in jobs:
        where = " ".join([j.get("location") or "", j.get("candidate_required_location") or ""]).lower()
        for name in ["france","ireland","germany","netherlands","belgium","spain","italy","portugal","sweden","norway","denmark","finland","austria","switzerland","united kingdom","uk","europe","emea"]:
            if name in where:
                countries[name] += 1
    skill_html = "".join([f"<li>{k} — {v}</li>" for k,v in top]) or "<li>No dominant skills today</li>"
    country_html = "".join([f"<li>{k.title()} — {v}</li>" for k,v in countries.most_common()]) or "<li>None detected</li>"
    return f"""
    <h3 style='margin:16px 0 6px 0;'>Insights</h3>
    <ul>{skill_html}</ul>
    <h4 style='margin:10px 0 6px 0;'>Locations Mentioned</h4>
    <ul>{country_html}</ul>
    """

def send_email(html, cfg):
    import ssl, smtplib
    from email.mime.text import MIMEText
    from email.utils import formatdate

    # Read envs (with safe port parsing)
    host = os.environ.get("SMTP_HOST", "")
    port_raw = os.environ.get("SMTP_PORT", "587")
    try:
        port = int(port_raw) if str(port_raw).strip() else 587
    except ValueError:
        port = 587

    user   = os.environ.get("SMTP_USER")
    pw     = os.environ.get("SMTP_PASS")
    sender = os.environ.get("EMAIL_FROM")
    to     = os.environ.get("EMAIL_TO")

    # Tell exactly what's missing
    missing = [name for name, val in [
        ("SMTP_HOST", host),
        ("SMTP_USER", user),
        ("SMTP_PASS", pw),
        ("EMAIL_FROM", sender),
        ("EMAIL_TO", to),
    ] if not val]

    if missing:
        print("Missing envs:", ", ".join(missing))
        return False  # always return False instead of None

    # Build the message
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = cfg.get("email_subject", "Daily Remote Jobs Digest")
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)

    # Try sending
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls(context=ctx)
            server.login(user, pw)
            server.sendmail(sender, [to], msg.as_string())
        return True
    except Exception as e:
        print("SMTP send failed:", repr(e))
        return False



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
    header = f"<h2 style='margin:0 0 10px 0;'>EU-Remote Java/Spring (0–1 yr) — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</h2>"
    insights = render_insights(jobs_new, cfg)
    footer = "<div style='font-size:12px;color:#888;margin-top:12px;'>This digest links to original postings (Greenhouse/Lever/Ashby/Remotive/RemoteOK/Adzuna) and your email alerts.</div>"
    return header + table + links_html + insights + footer

# ---------- main ----------

def main():
    cfg = load_json(CONFIG_PATH, {})
    # sensible defaults if user hasn't added new keys yet
    cfg.setdefault("title_must_include_any", ["backend", "java", "sde", "software developer", "software engineer", "sdet", "spring"])
    cfg.setdefault("title_exclude_any", ["senior", "staff", "principal", "lead", "manager", "architect", "director", "sr.", "sr "])
    cfg.setdefault("experience_filter", {
        "enabled": True,
        "max_years_inclusive": 1,
        "positive_markers_any": ["0-1", "0 to 1", "0 – 1", "0—1", "0/1", "0 years", "1 year", "≤1", "entry level", "junior", "graduate", "new grad", "early career", "l1", "level 1"],
        "negative_markers_any": ["2+ years", "2 years", "3+ years", "3 years", "mid-level", "mid level", "intermediate", "senior", "staff", "principal", "lead", "manager"]
    })

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

    # update seen after sending
    for j in all_jobs: 
        seen.add(j["id"])
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(list(seen))}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
