"""Build installable PWA assets without third-party dependencies."""
import json
import struct
import zlib
from pathlib import Path

ROOT = Path("public")
BASE = "/paragliding-weather/"

def png(size):
    # Dark-blue square with a simplified white paraglider canopy.
    def pixel(x,y):
        u=x/size;v=y/size
        blue=(25,55,81,255)
        canopy=((u-.5)/.34)**2+((v-.38)/.18)**2<=1 and .26<=v<=.45
        cords=(.34<=u<=.66 and .43<=v<=.72 and abs(u-.5)<(.72-v)*.6)
        pilot=((u-.5)/.045)**2+((v-.76)/.065)**2<=1
        if canopy:return (247,186,77,255)
        if cords and (abs(u-(.5-(.72-v)*.5))<.009 or abs(u-(.5+(.72-v)*.5))<.009):return (236,243,248,255)
        if pilot:return (236,243,248,255)
        return blue
    rows=b''.join(b'\x00'+bytes(c for x in range(size) for c in pixel(x,y)) for y in range(size))
    def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack(">IIBBBBB",size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')

def build():
    ROOT.mkdir(exist_ok=True)
    for size in (192,512):
        (ROOT/f"icon-{size}.png").write_bytes(png(size))
    manifest={
        "name":"Paragliding · Letová okna","short_name":"Letová okna",
        "description":"Předpověď a sledování letových oken pro paragliding",
        "id":BASE,"start_url":BASE,"scope":BASE,
        "display":"standalone","background_color":"#f0f5fa","theme_color":"#1c3a56",
        "lang":"cs","icons":[
            {"src":f"icon-{size}.png","sizes":f"{size}x{size}","type":"image/png","purpose":"any maskable"} for size in (192,512)
        ]}
    (ROOT/"manifest.webmanifest").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    # Network-first for the dashboard to avoid stale forecasts; no offline forecast promises.
    sw="""const CACHE='paragliding-shell-v1';
self.addEventListener('install',event=>{self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(self.clients.claim());});
self.addEventListener('fetch',event=>{
  if(event.request.mode!=='navigate')return;
  event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));
});
self.addEventListener('push',event=>{
  let data={};
  try{data=event.data?.json()||{};}catch(e){data={body:event.data?.text()||''};}
  event.waitUntil(self.registration.showNotification(data.title||'🪂 Letová okna',{
    body:data.body||'Aktualizace sledované předpovědi',
    icon:'icon-192.png',badge:'icon-192.png',
    tag:data.tag||'paragliding-update',data:{url:data.url||'./'}
  }));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil(self.clients.openWindow(event.notification.data?.url||'./'));
});
"""
    (ROOT/"sw.js").write_text(sw,encoding="utf-8")
    generator=r"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; connect-src 'none'">
<title>VAPID klíče · Letová okna</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#193652;background:#f1f6fa}
*{box-sizing:border-box}main{max-width:680px;margin:35px auto;padding:22px;background:white;border-radius:16px;box-shadow:0 5px 30px #17395413}
h1{font-size:25px;margin:0 0 10px}p{line-height:1.6;color:#536b80}
button{background:#193652;color:white;border:0;border-radius:9px;padding:13px 17px;font-size:15px;cursor:pointer}
button:disabled{opacity:.5}label{display:block;font-weight:700;margin-top:24px}
textarea{width:100%;height:95px;border:1px solid #c7d6e2;border-radius:9px;padding:12px;font:12px ui-monospace,monospace;resize:vertical;word-break:break-all}
.copy{margin-top:8px}.warning{background:#fff4e4;border-radius:9px;padding:12px 14px;font-size:14px;color:#6e4a19}
small{color:#71859a}#result[hidden]{display:none}
</style></head><body><main>
<h1>🪂 VAPID klíče pro notifikace</h1>
<p>Klíče se vytvářejí výhradně v tomto telefonu pomocí zabezpečeného generátoru prohlížeče. Stránka je nikam neposílá.</p>
<div class="warning">Soukromý klíč nikdy neposílej do chatu, e-mailu ani do veřejného repozitáře. Po zavření stránky se vygenerované hodnoty ztratí, proto nejdřív bezpečně ulož oba klíče.</div>
<p><button id="generate" type="button">Vygenerovat klíče</button></p>
<p id="status" role="status"></p>
<div id="result" hidden>
<label for="public">1. Veřejný klíč → GitHub Actions variable: VAPID_PUBLIC_KEY</label>
<textarea id="public" readonly spellcheck="false"></textarea><button class="copy" data-target="public" type="button">Kopírovat veřejný klíč</button>
<label for="private">2. Soukromý klíč → GitHub Actions secret: VAPID_PRIVATE_KEY</label>
<textarea id="private" readonly spellcheck="false"></textarea><button class="copy" data-target="private" type="button">Kopírovat soukromý klíč</button>
<p><small>VAPID používá eliptickou křivku P-256. Veřejný klíč je 65bajtový nekomprimovaný bod, soukromý klíč je 32bajtová hodnota, obojí Base64URL.</small></p>
</div>
</main><script>
const btn=document.getElementById('generate'),status=document.getElementById('status'),result=document.getElementById('result');
function decode(s){const b=atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4));return Uint8Array.from(b,c=>c.charCodeAt(0));}
function encode(bytes){let b='';for(const n of bytes)b+=String.fromCharCode(n);return btoa(b).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
btn.onclick=async()=>{
  btn.disabled=true;result.hidden=true;status.textContent='Generuji bezpečné klíče…';
  try{
    if(!crypto.subtle)throw Error('Tento prohlížeč nepodporuje Web Crypto');
    const pair=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']);
    const jwk=await crypto.subtle.exportKey('jwk',pair.privateKey);
    const x=decode(jwk.x),y=decode(jwk.y),d=decode(jwk.d);
    if(x.length!==32||y.length!==32||d.length!==32)throw Error('Neočekávaná délka klíče');
    const pub=new Uint8Array(65);pub[0]=4;pub.set(x,1);pub.set(y,33);
    document.getElementById('public').value=encode(pub);
    document.getElementById('private').value=encode(d);
    result.hidden=false;status.textContent='Hotovo. Ulož oba klíče do GitHubu.';
  }catch(e){status.textContent='Chyba: '+e.message;}finally{btn.disabled=false;}
};
document.querySelectorAll('.copy').forEach(b=>b.onclick=async()=>{
  const el=document.getElementById(b.dataset.target);
  try{await navigator.clipboard.writeText(el.value);status.textContent='Klíč zkopírován do schránky.';}
  catch(e){el.focus();el.select();status.textContent='Automatické kopírování selhalo. Označený klíč zkopíruj ručně.';}
});
</script></body></html>"""
    (ROOT/"vapid-keys.html").write_text(generator,encoding="utf-8")

if __name__=="__main__":build()
