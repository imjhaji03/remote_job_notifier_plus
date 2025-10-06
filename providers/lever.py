import requests
from urllib.parse import quote_plus

def _cat_val(cats, key):
    if not isinstance(cats, dict):
        return ""
    v = cats.get(key)
    return v if isinstance(v, str) else ""

def fetch(company: str):
    url = f"https://api.lever.co/v0/postings/{quote_plus(company)}?mode=json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json() or []
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        # Build a safe tag string from known string fields
        tag_parts = []
        for k in ("team", "department", "commitment", "location"):
            val = _cat_val(cats, k)
            if val:
                tag_parts.append(val)
        tags = " ".join(tag_parts)

        jobs.append({
            "source": "lever",
            "title": j.get("text"),
            "company": j.get("company", company),
            "location": _cat_val(cats, "location"),
            "candidate_required_location": _cat_val(cats, "location"),
            "tags": tags,
            "description": j.get("descriptionPlain") or j.get("description") or "",
            "url": j.get("hostedUrl") or j.get("applyUrl"),
            "region": "",
            "posted_at": j.get("createdAt"),
        })
    return jobs
