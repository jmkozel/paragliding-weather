#!/usr/bin/env python3
"""Conservative model screening, NOT a paragliding safety forecast."""
import html
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Prague")
# Coordinates approximate the terrain, not exact launch pads. Verify on-site.
# Values: min/max 10m model wind, max gust (m/s), accepted direction FROM.
SITES = [
 ("Cukrák",49.9381,14.3354,2,8,10,[(270,360)]),
 ("Staňkovka",49.9686,14.3251,3,8,10,[(110,170)]),
 ("Karlík",49.950,14.258,3,8,10,[(135,180)]),
 ("Řevničov",50.183,13.809,3,9,12,[(160,250)]),
 ("Suchomasty / Klonk",49.907,14.064,3,6,8,[(200,260)]),
 ("Raná JV",50.4065,13.7710,2,6,10,[(70,190)]),
 ("Raná SZ",50.4065,13.7710,2,6,10,[(250,360),(0,20)]),
 ("Jeviněves",50.341,14.337,3,8,11,[(90,160)]),
 ("Říp JV",50.386,14.289,2,6,10,[(90,160)]),
 ("Říp JZ",50.386,14.289,2,6,10,[(200,270)]),
 ("Říp SZ",50.386,14.289,2,6,10,[(300,330)]),
 ("Koukolova hora",49.915,14.103,2,6,10,[(285,360)]),
 ("Beroun / vysílač",49.965,14.076,3,8,10,[(100,170)]),
]
HOURLY = [
 "wind_speed_10m","wind_direction_10m","wind_gusts_10m",
 "wind_speed_80m","wind_direction_80m","precipitation",
 "precipitation_probability","visibility","weather_code",
 "cloud_cover","cloud_cover_low","cape",
]
BAD_CODES = {45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,
             80,81,82,85,86,95,96,99}

def fetch(lat, lon):
    args = {
        "latitude":lat,"longitude":lon,"timezone":"Europe/Prague",
        "forecast_days":5,"wind_speed_unit":"ms",
        "hourly":",".join(HOURLY),"daily":"sunrise,sunset",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(args)
    with urllib.request.urlopen(url, timeout=35) as response:
        obj = json.load(response)
    if "hourly" not in obj or "daily" not in obj:
        raise ValueError("Open-Meteo nevrátilo hodinová/denní data")
    return obj

def direction_ok(direction, ranges):
    return any(lo <= direction <= hi for lo,hi in ranges)

def get(h, key, i):
    values = h.get(key)
    return values[i] if values is not None and i < len(values) else None

def screening(site, h, i):
    _,_,_,minimum,maximum,gust_limit,ranges = site
    required = ["wind_speed_10m","wind_direction_10m","wind_gusts_10m",
                "wind_speed_80m","precipitation","visibility","weather_code"]
    v = {key:get(h,key,i) for key in required}
    if any(x is None for x in v.values()):
        return False, "chybí klíčová meteorologická data"
    w = v["wind_speed_10m"]
    g = v["wind_gusts_10m"]
    upper = v["wind_speed_80m"]
    if not (minimum <= w <= maximum and g <= gust_limit):
        return False, "vítr/nárazy mimo limit"
    if not direction_ok(v["wind_direction_10m"],ranges):
        return False, "nevhodný směr větru"
    if v["precipitation"] > 0.1 or v["visibility"] < 5000 or v["weather_code"] in BAD_CODES:
        return False, "srážky, dohlednost nebo nepříznivé počasí"
    # Cautious high-wind flag, NOT a turbulence prediction.
    if upper > 12 or upper-w > 7:
        return False, "silný vítr / rozdíl rychlostí v 80 m"
    probability = get(h,"precipitation_probability",i)
    cape = get(h,"cape",i)
    if probability is not None and probability >= 60:
        return False, "vysoká pravděpodobnost srážek"
    if cape is not None and cape >= 500:
        return False, "zvýšený konvektivní potenciál"
    return True, ""

def solar_intervals(data):
    daily=data["daily"]
    return {d:(datetime.fromisoformat(a),datetime.fromisoformat(b))
            for d,a,b in zip(daily["time"],daily["sunrise"],daily["sunset"])}

def find_windows(site, data, now):
    h=data["hourly"]; solar=solar_intervals(data)
    slots=[]
    for i,t in enumerate(h["time"]):
        start=datetime.fromisoformat(t)
        day=start.date().isoformat()
        if day not in solar:
            continue
        sunrise,sunset=solar[day]
        # Hourly forecast represents [HH:00, HH+1:00). Clip to actual daylight.
        begin=max(start,sunrise,now.replace(tzinfo=None))
        end=min(start+timedelta(hours=1),sunset)
        good,_=screening(site,h,i)
        if good and end>begin:
            slots.append((begin,end,i))
    groups=[]; current=[]
    for slot in slots:
        if current and slot[0]>current[-1][1]:
            groups.append(current);current=[]
        current.append(slot)
    if current:groups.append(current)
    # Require at least 60 continuous minutes after clipping to daylight.
    return [g for g in groups if (g[-1][1]-g[0][0]).total_seconds()>=3600]

def fmt_time(dt):
    return dt.strftime("%H:%M")

def window_details(site, data, group):
    h=data["hourly"]; indices=[x[2] for x in group]
    def bounds(key):
        vals=[get(h,key,i) for i in indices]
        vals=[x for x in vals if x is not None]
        return (min(vals),max(vals)) if vals else None
    wind=bounds("wind_speed_10m");gust=bounds("wind_gusts_10m")
    upper=bounds("wind_speed_80m"); cloud=bounds("cloud_cover")
    low=bounds("cloud_cover_low");rain=bounds("precipitation_probability")
    dirs=[get(h,"wind_direction_10m",i) for i in indices]
    dirs=[int(round(x))%360 for x in dirs if x is not None]
    def span(pair,unit="",precision=1):
        return (f"{pair[0]:.{precision}f}–{pair[1]:.{precision}f}{unit}" if pair else "bez dat")
    return (f"vítr 10 m {span(wind,' m/s')}, nárazy {span(gust,' m/s')}, "
            f"směr odkud {min(dirs)}–{max(dirs)}°; "
            f"vítr 80 m {span(upper,' m/s')}; "
            f"oblačnost {span(cloud,' %',0)} (nízká {span(low,' %',0)}); "
            f"pravd. srážek {span(rain,' %',0)}")

def build_report(now, sites=SITES, loader=fetch):
    by_day=defaultdict(list); errors=[]; checked=0
    cache={}
    for site in sites:
        name,lat,lon,*_=site
        try:
            key=(lat,lon)
            if key not in cache:cache[key]=loader(lat,lon)
            data=cache[key]
            for group in find_windows(site,data,now):
                start,end=group[0][0],group[-1][1]
                by_day[start.date()].append((name,start,end,window_details(site,data,group)))
            checked+=1
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    title=f"🪂 PARAGLIDING | 5 dní | {now:%d.%m.%Y %H:%M}"
    lines=[title,"Modelový screening Open-Meteo. Kandidát ≠ bezpečné letové okno.",""]
    if by_day:
        lines+=["PŘEHLED DNŮ S KANDIDÁTNÍMI OKNY",""]
        for day in sorted(by_day):
            lines.append(day.strftime("%A %d.%m.%Y"))
            for name,start,end,detail in sorted(by_day[day],key=lambda x:x[1]):
                lines.append(f"  • {name}: {fmt_time(start)}–{fmt_time(end)}")
            lines.append("")
        lines+=["PODROBNOSTI",""]
        for day in sorted(by_day):
            lines.append(day.strftime("%d.%m.%Y"))
            for name,start,end,detail in sorted(by_day[day],key=lambda x:x[1]):
                lines.append(f"  {name} | {fmt_time(start)}–{fmt_time(end)}")
                lines.append(f"    {detail}")
                lines.append("    Svah: kandidát dle větru | Termika: nelze spolehlivě určit | XC: nelze spolehlivě určit")
            lines.append("")
    else:
        lines+=["Žádné kandidátní okno ≥ 60 minut podle dostupných dat.",
                "To samo o sobě neznamená, že nikde nelze bezpečně létat.",""]
    if errors:
        lines+=["NEÚPLNÁ DATA / CHYBY (neinterpretovat jako špatné počasí):"]+errors+[""]
    lines+=["METODIKA A OMEZENÍ:",
            "Jen intervaly mezi místním východem a západem slunce, min. 60 minut po ořezu.",
            "Vítr 10 m a 80 m je MODEL pro souřadnice terénu, nikoli měření na startu či výškový profil nad startem.",
            "Předběžně vyloučeny vysoké nárazy, srážky, špatná dohlednost, vybrané jevy, silný vítr 80 m a zvýšený CAPE.",
            "Oblačnost je orientační, termika/XC a turbulence nejsou spolehlivě vyhodnoceny.",
            "Model neověřuje lokální rotory, aktuální stanice, fronty ani reálné podmínky na startu.",
            "Souřadnice některých terénů jsou přibližné a vyžadují ověření.",
            "Před letem nezávisle ověř aktuální měření, výškový vítr, vývoj počasí a místní pravidla.",
            f"Zpracováno {checked}/{len(sites)} sektorů; chyba dat u {len(errors)} sektorů."]
    return "\n".join(lines),sum(map(len,by_day.values())),errors

def main():
    now=datetime.now(TZ)
    body,count,errors=build_report(now)
    print(body)
    sender=os.getenv("SMTP_USER")
    password=os.getenv("SMTP_APP_PASSWORD")
    if not sender or not password:
        print("\nEmail NOT sent: configure SMTP_USER and SMTP_APP_PASSWORD secrets.")
        return
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=os.getenv("REPORT_TO","jmkozel@gmail.com")
    msg["Subject"]=f"🪂 Paragliding | {now:%d.%m.%Y} | {count} kandidátních oken"
    msg.set_content(body)
    # Readable HTML email; no external images or scripts.
    markup="<html><body style='font-family:Arial,sans-serif;line-height:1.55;max-width:760px;margin:auto'>"
    markup+="<pre style='white-space:pre-wrap;font-family:Arial,sans-serif;font-size:14px'>"+html.escape(body)+"</pre></body></html>"
    msg.add_alternative(markup,subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(sender,password)
        smtp.send_message(msg)
    print("Email sent.")

if __name__=="__main__":
    main()
