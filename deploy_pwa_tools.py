"""Deploy PWA utility assets while retaining the currently published dashboard."""
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from pwa_assets import build

URL="https://jmkozel.github.io/paragliding-weather/"
req=Request(URL,headers={"User-Agent":"paragliding-pwa-setup/1","Cache-Control":"no-cache"})
with urlopen(req,timeout=30) as response:
    page=response.read()
if b'<html' not in page.lower() or b'Letov' not in page:
    raise RuntimeError("Published dashboard could not be verified; refusing to replace it")
out=Path("public")
out.mkdir(exist_ok=True)
public_key=os.environ.get("VAPID_PUBLIC_KEY","").strip()
if public_key:
    text=page.decode("utf-8")
    pattern=r"const VAPID_KEY=(?:\\\"[^\\\"]*\\\"|'[^']*');"
    updated,count=re.subn(pattern,"const VAPID_KEY="+json.dumps(public_key)+";",text,count=1)
    if count!=1:
        raise RuntimeError("VAPID key placeholder not found in existing dashboard")
    page=updated.encode("utf-8")
    print("Inserted VAPID public key into existing dashboard")
else:
    print("Warning: VAPID_PUBLIC_KEY not configured; notification opt-in remains disabled")
(out/"index.html").write_bytes(page)
(out/".nojekyll").write_text("",encoding="utf-8")
build()
assert (out/"vapid-keys.html").exists()
print("Published PWA utility assets with unchanged existing dashboard; weather API not required.")
