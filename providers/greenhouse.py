import requests
from urllib.parse import quote_plus

def fetch(board_token: str, content=True):
    url = f"https://boards-api.greenhouse.io/v1/boards/{quote_plus(board_token)}/jobs"
    if content:
        url += "?content=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json() or {}
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "source": "greenhouse",
            "title": j.get("title"),
            "company": board_token,
            "location": (j.get("location") or {}).get("name", ""),
            "candidate_required_location": (j.get("location") or {}).get("name", ""),
            "tags": "",
            "description": (j.get("content") or ""),
            "url": j.get("absolute_url"),
            "region": "",
            "posted_at": j.get("updated_at"),
        })
    return jobs
