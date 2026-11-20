"""Diagnose whether GitHub Actions can reach Cloudflare Worker endpoints.

Never prints authorization credentials or subscription data.
"""
import json
import os
import urllib.error
import urllib.request

BASE="https://paragliding-push.jmkozel.workers.dev"

def probe(name,path,authorized=False):
    headers={"Accept":"application/json","User-Agent":"ParaglidingPushDiagnostic/1.0"}
    if authorized:
        token=os.environ.get("PUSH_API_TOKEN","")
        if not token:
            print(f"{name}: missing PUSH_API_TOKEN in GitHub Actions secrets")
            return
        headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(BASE+path,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            report(response,name)
    except urllib.error.HTTPError as exc:
        report(exc,name)
    except Exception as exc:
        print(f"{name}: network error ({type(exc).__name__})")

def report(response,name):
    status=response.status
    mime=response.headers.get("Content-Type","unknown").split(";")[0]
    cf_ray=response.headers.get("CF-Ray","not provided")
    raw=response.read(500)
    error="none"
    if mime=="application/json":
        try:
            payload=json.loads(raw)
            if isinstance(payload,dict):
                error=str(payload.get("error","none"))[:100]
        except (ValueError,UnicodeDecodeError):
            error="invalid JSON"
    print(f"{name}: HTTP {status}, content-type={mime}, CF-Ray={cf_ray}, API error={error}")
    if status==403 and mime!="application/json":
        print(f"{name}: response is not from our JSON API; investigate Cloudflare edge rules or outbound proxy")

if __name__=="__main__":
    probe("Health (public)","/health")
    probe("Subscriptions (no token)","/subscriptions")
    probe("Subscriptions (with token)","/subscriptions",authorized=True)
