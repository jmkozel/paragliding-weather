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
if __name__=="__main__":build()
