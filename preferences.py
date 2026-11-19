"""Shared decisions stored in Cloudflare KV via the public Worker API."""
import json
import urllib.request

API="https://paragliding-control.jmkozel.workers.dev/preferences"

def load():
    req=urllib.request.Request(API,headers={"User-Agent":"paragliding-weather/2"})
    with urllib.request.urlopen(req,timeout=25) as response:
        obj=json.load(response)
    if obj.get("complete") is not True or not isinstance(obj.get("preferences"),list):
        raise RuntimeError("Incomplete Cloudflare preferences response")
    result={"days":{},"windows":{},"issue_urls":{}}
    for item in obj["preferences"]:
        try:
            day,site=item["key"].split("|",1)
            action=item["value"]
            if site=="*" and action=="exclude": result["days"][day]=True
            elif site!="*" and action in ("exclude","watch"): result["windows"][day+"|"+site]=action
        except (KeyError,ValueError,TypeError):
            continue
    return result

def excluded(state,day,site):
    return bool(state.get("days",{}).get(day) or state.get("windows",{}).get(day+"|"+site)=="exclude")
