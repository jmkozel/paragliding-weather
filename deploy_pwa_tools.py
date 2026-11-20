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
if not public_key:
    raise RuntimeError("VAPID_PUBLIC_KEY is missing from GitHub Actions variables")
if len(public_key) < 80 or len(public_key) > 100:
    raise RuntimeError("VAPID_PUBLIC_KEY has unexpected length; check GitHub variable")

text=page.decode("utf-8")
pattern=r'const VAPID_KEY="[^"]*";'
updated,count=re.subn(pattern,lambda _: "const VAPID_KEY="+json.dumps(public_key)+";",text,count=1)
if count:
    text=updated
    print("Updated VAPID public key in existing dashboard")
else:
    print("Existing dashboard has no push UI; adding independent notification setup page")
    link='<div style="margin:12px auto;max-width:980px;padding:12px;background:#e8f3ff;border-radius:10px"><a href="./push-setup.html" style="font-weight:700;color:#123f65">🔔 Zapnout mobilní notifikace</a></div>'
    if '</body>' not in text:
        raise RuntimeError("Existing dashboard has no closing body tag")
    text=text.replace('</body>',link+'</body>',1)
page=text.encode("utf-8")
setup=r"""<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mobilní notifikace · Letová okna</title><meta name="theme-color" content="#193652">
<link rel="manifest" href="./manifest.webmanifest">
<style>body{font:16px system-ui;background:#f0f5fa;color:#193652;margin:0;padding:20px}
main{max-width:580px;margin:28px auto;background:white;padding:24px;border-radius:16px}
button{border:0;background:#193652;color:white;border-radius:9px;padding:14px 18px;font:inherit;margin:8px 8px 8px 0}
button:disabled{opacity:.5}p{line-height:1.5}a{color:#185d93}</style></head><body><main>
<p><a href="./">← Zpět na předpověď</a></p><h1>🔔 Mobilní notifikace</h1>
<p id="status">Kontroluji dostupnost…</p>
<button id="enable" hidden>Zapnout notifikace</button><button id="disable" hidden>Vypnout notifikace</button>
</main><script>
const VAPID_KEY=__PUBLIC_KEY__;
const PUSH_URL='https://paragliding-push.jmkozel.workers.dev';
const status=document.getElementById('status'),enable=document.getElementById('enable'),disable=document.getElementById('disable');
function bytes(s){return Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4)),c=>c.charCodeAt(0))}
async function refresh(){
 if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){status.textContent='Tento prohlížeč nepodporuje push notifikace.';return}
 try{const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();
 status.textContent=sub?'Notifikace jsou zapnuté.':'Notifikace zatím nejsou zapnuté.';
 enable.hidden=!!sub;disable.hidden=!sub}
 catch(e){status.textContent='Chyba: '+e.message}
}
enable.onclick=async()=>{
 enable.disabled=true;status.textContent='Registruji telefon…';
 try{if(await Notification.requestPermission()!=='granted')throw Error('Povolení nebylo uděleno');
 const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(VAPID_KEY)});
 const r=await fetch(PUSH_URL+'/subscriptions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({subscription:sub.toJSON()})});
 if(!r.ok){await sub.unsubscribe();throw Error('Server odmítl registraci: HTTP '+r.status)}
 await refresh()}catch(e){status.textContent='Registrace selhala: '+e.message}finally{enable.disabled=false}
};
disable.onclick=async()=>{
 disable.disabled=true;
 try{const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();
 if(sub){const r=await fetch(PUSH_URL+'/subscriptions',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({subscription:sub.toJSON()})});
 if(!r.ok)throw Error('Odhlášení selhalo: HTTP '+r.status);await sub.unsubscribe()}
 await refresh()}catch(e){status.textContent='Chyba: '+e.message}finally{disable.disabled=false}
};
navigator.serviceWorker.register('./sw.js').then(refresh).catch(e=>status.textContent='Chyba registrace aplikace: '+e.message);
</script></body></html>"""
(out/"push-setup.html").write_text(setup.replace("__PUBLIC_KEY__",json.dumps(public_key)),encoding="utf-8")
(out/"index.html").write_bytes(page)
(out/".nojekyll").write_text("",encoding="utf-8")
build()
assert (out/"vapid-keys.html").exists()
print("Published PWA utility assets with unchanged existing dashboard; weather API not required.")
