"""Deploy PWA utility assets while retaining the currently published dashboard."""
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
(out/"index.html").write_bytes(page)
(out/".nojekyll").write_text("",encoding="utf-8")
build()
assert (out/"vapid-keys.html").exists()
print("Published PWA utility assets with unchanged existing dashboard; weather API not required.")
