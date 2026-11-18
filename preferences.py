"""Shared preferences from GitHub issues, no credentials exposed in the website.
Issue title: PG|watch|YYYY-MM-DD|SITE or PG|exclude|YYYY-MM-DD|SITE
SITE is a configured name or '*' for an entire day.
Closing an issue restores the item.
"""
import json
import os
import urllib.request
from datetime import date

REPO="jmkozel/paragliding-weather"
def load():
    url=f"https://api.github.com/repos/{REPO}/issues?state=open&per_page=100"
    headers={"Accept":"application/vnd.github+json","User-Agent":"paragliding-weather"}
    token=os.getenv("GITHUB_TOKEN")
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=25) as response:
        issues=json.load(response)
    result={"days":{},"windows":{},"issue_urls":{}}
    for issue in issues:
        if "pull_request" in issue: continue
        parts=issue.get("title","").split("|",3)
        if len(parts)!=4 or parts[0]!="PG" or parts[1] not in ("watch","exclude"): continue
        _,action,day,site=parts
        try: date.fromisoformat(day)
        except ValueError: continue
        if site=="*" and action=="exclude":
            result["days"][day]=True
            result["issue_urls"]["day:"+day]=issue["html_url"]
        elif site!="*":
            key=day+"|"+site
            result["windows"][key]=action
            result["issue_urls"][key]=issue["html_url"]
    return result

def excluded(state,day,site):
    return bool(state.get("days",{}).get(day) or state.get("windows",{}).get(day+"|"+site)=="exclude")
