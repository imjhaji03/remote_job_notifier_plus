import requests
from urllib.parse import quote_plus

def fetch(company: str):
    url = f"https://api.lever.co/v0/postings/{quote_plus(company)}?mode=json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json() or []
    jobs = []
    for j in data:
        jobs.append({
            "source": "lever",
            "title": j.get("text"),
            "company": j.get("company", company),
            "location": (j.get("categories") or {}).get("location") or "",
            "candidate_required_location": (j.get("categories") or {}).get("location") or "",
            "tags": " ".join(j.get("lists", []) or []),
            "description": j.get("descriptionPlain") or j.get("description") or "",
            "url": j.get("hostedUrl") or j.get("applyUrl"),
            "region": "",
            "posted_at": j.get("createdAt"),
        })
    return jobs
