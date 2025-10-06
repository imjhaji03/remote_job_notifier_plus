import requests
from urllib.parse import quote_plus

def fetch(job_board_name: str, include_comp=False):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{quote_plus(job_board_name)}"
    if include_comp:
        url += "?includeCompensation=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json() or {}
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "source": "ashby",
            "title": j.get("title"),
            "company": job_board_name,
            "location": j.get("location") or "",
            "candidate_required_location": j.get("location") or "",
            "tags": "",
            "description": j.get("descriptionPlain") or j.get("descriptionHtml") or "",
            "url": j.get("jobUrl"),
            "region": "",
            "posted_at": j.get("publishedAt"),
            "is_remote": j.get("isRemote"),
        })
    return jobs
