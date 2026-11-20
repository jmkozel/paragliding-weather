"""Send a test Web Push to registered PWA devices. No email behavior is changed."""
import json
import os
import sys
import urllib.request
import urllib.error
from pywebpush import webpush, WebPushException

API="https://paragliding-push.jmkozel.workers.dev/subscriptions"
PAGE="https://jmkozel.github.io/paragliding-weather/"

def subscriptions():
    req=urllib.request.Request(API,headers={"Authorization":"Bearer "+os.environ["PUSH_API_TOKEN"]})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            return json.load(r)["subscriptions"]
    except urllib.error.HTTPError as exc:
        content=exc.read(600).decode("utf-8","replace")
        kind="Cloudflare edge" if "cloudflare" in exc.headers.get("Server","").lower() else "unknown server"
        print(f"Push API failed: HTTP {exc.code}; server={kind}; content-type={exc.headers.get('Content-Type','unknown')}",file=sys.stderr)
        if content.strip().startswith("{"):
            try:
                payload=json.loads(content)
                print("API error: "+str(payload.get("error","unspecified")),file=sys.stderr)
            except ValueError:
                pass
        else:
            print("API returned non-JSON response (possibly Cloudflare security blocking)",file=sys.stderr)
        raise RuntimeError("Could not access push subscriptions; no notifications were sent") from None

def deliver(title,body,tag="paragliding-update",url=PAGE):
    devices=subscriptions()
    if not devices:
        print("No subscribed devices yet")
        return 0
    sent=0
    for item in devices:
        try:
            webpush(
                subscription_info=item["subscription"],
                data=json.dumps({"title":title,"body":body,"tag":tag,"url":url},ensure_ascii=False),
                vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                vapid_claims={"sub":"mailto:"+os.environ.get("VAPID_CONTACT","jmkozel@gmail.com")},
                ttl=3600,
            )
            sent+=1
        except WebPushException as exc:
            print("Web Push failed for device "+item["id"][:8]+": "+str(exc),file=sys.stderr)
    print(f"Push delivered to {sent}/{len(devices)} endpoints")
    if sent==0:raise RuntimeError("No push delivery succeeded")
    return sent

if __name__=="__main__":
    deliver("🪂 Test notifikací","Pokud tuto zprávu vidíš, mobilní notifikace fungují!",tag="paragliding-test")
