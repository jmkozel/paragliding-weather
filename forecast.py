#!/usr/bin/env python3
"""Conservative model screening, NOT a paragliding safety forecast."""
import html
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
import time
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

def open_with_retry(request, timeout=35, attempts=3):
    """Retry transient network errors; never fabricate weather data."""
    last = None
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except (OSError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Weather API unavailable after {attempts} attempts: {last}") from last

def fetch(lat, lon):
    args = {
        "latitude":lat,"longitude":lon,"timezone":"Europe/Prague",
        "forecast_days":5,"wind_speed_unit":"ms",
        "hourly":",".join(HOURLY),"daily":"sunrise,sunset",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(args)
    with open_with_retry(url, timeout=35) as response:
        obj = json.load(response)
    if "hourly" not in obj or "daily" not in obj:
        raise ValueError("Open-Meteo nevrátilo hodinová/denní data")
    return obj

def fetch_all_sites():
    """One multi-location Open-Meteo request; avoids 10+ requests per run."""
    locations=list(dict.fromkeys((s[1],s[2]) for s in SITES))
    args={
        "latitude":",".join(str(p[0]) for p in locations),
        "longitude":",".join(str(p[1]) for p in locations),
        "timezone":"Europe/Prague",
        "forecast_days":5,"wind_speed_unit":"ms",
        "hourly":",".join(HOURLY),"daily":"sunrise,sunset",
    }
    url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode(args)
    req=urllib.request.Request(url,headers={"User-Agent":"paragliding-weather/1.0"})
    with open_with_retry(req,timeout=35) as response:
        payload=json.load(response)
    results=payload if isinstance(payload,list) else [payload]
    if len(results)!=len(locations):
        raise ValueError(f"Expected {len(locations)} locations, got {len(results)}")
    if any("hourly" not in result or "daily" not in result for result in results):
        raise ValueError("Incomplete Open-Meteo multi-location response")
    return dict(zip(locations,results))

MODELS = {
    "ICON-D2": "icon_d2",
    "ICON-EU": "icon_eu",
    "ECMWF": "ecmwf_ifs025",
    "GFS": "gfs_seamless",
}
# Separate model calls make the response schema explicit. Fail closed on errors.
MODEL_HOURLY = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation"]

def fetch_model_comparison():
    locations=list(dict.fromkeys((s[1],s[2]) for s in SITES))
    output={}
    for label,model in MODELS.items():
        args={
            "latitude":",".join(str(p[0]) for p in locations),
            "longitude":",".join(str(p[1]) for p in locations),
            "timezone":"Europe/Prague",
            "forecast_days":5,
            "wind_speed_unit":"ms",
            "hourly":",".join(MODEL_HOURLY),
            "models":model,
        }
        url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode(args)
        req=urllib.request.Request(url,headers={"User-Agent":"paragliding-weather/1.1"})
        with open_with_retry(req,timeout=35) as response:
            payload=json.load(response)
        results=payload if isinstance(payload,list) else [payload]
        if len(results)!=len(locations):
            raise ValueError(f"{label}: unexpected location count")
        for location,data in zip(locations,results):
            h=data.get("hourly",{})
            if not all(h.get(k) and len(h[k])==len(h.get("time",[])) for k in MODEL_HOURLY):
                raise ValueError(f"{label}: incomplete hourly wind data")
            output.setdefault(location,{})[label]=h
    return output

def model_consensus(site, models, time):
    """Conservative consensus: at least 3/4 pass; no severe outlier.
    Returns status and per-model values. Missing data never counts as agreement.
    """
    _,_,_,minimum,maximum,gust_limit,ranges=site
    rows=[]
    for label,h in models.items():
        try:
            i=h["time"].index(time)
            w=h["wind_speed_10m"][i]
            d=h["wind_direction_10m"][i]
            g=h["wind_gusts_10m"][i]
            rain=h["precipitation"][i]
            if None in (w,d,g,rain): raise ValueError("missing")
            passed=minimum<=w<=maximum and g<=gust_limit and direction_ok(d,ranges) and rain<=0.1
            severe=w>maximum+2 or g>gust_limit+3 or rain>=0.5
            rows.append({"model":label,"wind":w,"direction":d,"gust":g,"rain":rain,
                         "pass":passed,"severe":severe})
        except (ValueError,IndexError,KeyError,TypeError):
            rows.append({"model":label,"wind":None,"direction":None,
                         "gust":None,"rain":None,"pass":False,"severe":True})
    good=sum(row["pass"] for row in rows)
    severe=any(row["severe"] for row in rows)
    status="good" if good>=3 and not severe else ("uncertain" if good>=2 and not severe else "bad")
    return status,rows

def consensus_windows(site,data,models,now):
    """Only good consensus hours form published windows."""
    h=data["hourly"]
    solar=solar_intervals(data)
    slots=[]
    details={}
    for i,t in enumerate(h["time"]):
        start=datetime.fromisoformat(t)
        day=start.date().isoformat()
        if day not in solar: continue
        sunrise,sunset=solar[day]
        begin=max(start,sunrise,now.replace(tzinfo=None))
        end=min(start+timedelta(hours=1),sunset)
        status,rows=model_consensus(site,models,t)
        details[i]=(status,rows)
        good,_=screening(site,h,i)
        if good and status=="good" and end>begin:
            slots.append((begin,end,i))
    groups=[]
    current=[]
    for slot in slots:
        if current and slot[0]>current[-1][1]:
            groups.append(current)
            current=[]
        current.append(slot)
    if current:groups.append(current)
    groups=[g for g in groups if (g[-1][1]-g[0][0]).total_seconds()>=3600]
    return groups,details

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

def risk_notes(data, group):
    """Heuristic warnings, not a local turbulence or flight-safety prediction."""
    h=data["hourly"]
    notes=[]
    for _,_,i in group:
        w=get(h,"wind_speed_10m",i)
        gust=get(h,"wind_gusts_10m",i)
        d10=get(h,"wind_direction_10m",i)
        d80=get(h,"wind_direction_80m",i)
        upper=get(h,"wind_speed_80m",i)
        low=get(h,"cloud_cover_low",i)
        prob=get(h,"precipitation_probability",i)
        if w is not None and gust is not None and w>0 and gust/w>=2.0:
            notes.append("Výrazné nárazy vůči průměrnému větru")
        if d10 is not None and d80 is not None:
            difference=abs((d80-d10+180)%360-180)
            if difference>=35:
                notes.append("Výrazná změna směru větru mezi 10 a 80 m")
        if w is not None and upper is not None and upper-w>=4:
            notes.append("Zřetelný nárůst rychlosti větru v 80 m")
        if low is not None and low>=90:
            notes.append("Velmi vysoká nízká oblačnost; ověř výšku základny a dohlednost")
        if prob is not None and prob>=40:
            notes.append("Zvýšená pravděpodobnost srážek")
    return list(dict.fromkeys(notes))

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

def build_report(now, sites=SITES, loader=None):
    if loader is None:
        shared=fetch_all_sites()
        loader=lambda lat,lon:shared[(lat,lon)]
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
            lines.append(cz_day(day))
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


DAYS = ["pondělí","úterý","středa","čtvrtek","pátek","sobota","neděle"]
def cz_day(date):
    return f"{DAYS[date.weekday()].capitalize()} {date:%d.%m.%Y}"

def metrics(data, group):
    h=data["hourly"]
    ids=[part[2] for part in group]
    def bounds(key):
        vals=[get(h,key,i) for i in ids]
        vals=[v for v in vals if v is not None]
        return (min(vals),max(vals)) if vals else None
    return {key:bounds(key) for key in (
        "wind_speed_10m","wind_gusts_10m","wind_direction_10m",
        "wind_speed_80m","cloud_cover","cloud_cover_low",
        "precipitation_probability")}

def display_range(value, unit="", digits=1):
    if value is None: return "bez dat"
    a,b=value
    return f"{a:.{digits}f}–{b:.{digits}f}{unit}" if abs(a-b)>0.049 else f"{a:.{digits}f}{unit}"

def render_html(now, sites=SITES, loader=None):
    if loader is None:
        shared=fetch_all_sites()
        loader=lambda lat,lon:shared[(lat,lon)]
    """Compact HTML email with real in-message navigation links (no fake watch buttons)."""
    by_day=defaultdict(list); errors=[]; cache={}
    for site in sites:
        name,lat,lon,*_=site
        try:
            key=(lat,lon)
            if key not in cache: cache[key]=loader(lat,lon)
            data=cache[key]
            for group in find_windows(site,data,now):
                start,end=group[0][0],group[-1][1]
                by_day[start.date()].append((name,start,end,metrics(data,group)))
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    esc=html.escape
    parts=["<!doctype html><html lang='cs'><head><meta charset='utf-8'></head>",
           "<body style='margin:0;padding:10px 6px;background:#f3f6fa;font-family:Arial,Helvetica,sans-serif;color:#203044'>",
           "<table role='presentation' cellpadding='0' cellspacing='0' style='max-width:690px;width:100%;margin:auto;border-collapse:collapse'>",
           "<tr><td style='padding:13px 17px;background:#16324f;color:#fff'>",
           "<div style='font-size:12px;letter-spacing:.6px;color:#d7e7f3'>🪂 PARAGLIDING · 5 DNÍ</div>",
           f"<div style='font-size:20px;font-weight:bold;margin-top:3px'>{now:%d.%m.%Y}</div>",
           "</td></tr><tr><td style='padding:14px 16px;background:white'>"]
    count=sum(len(v) for v in by_day.values())
    parts.append(f"<div style='font-size:13px;color:#586a7e;margin-bottom:9px'><b>{count} kandidátních oken</b> · {len(by_day)} dní · aktualizace {now:%H:%M}</div>")
    if not by_day:
        parts.append("<p style='font-size:14px'>Žádné kandidátní okno alespoň 60 minut podle dostupného modelu. Neznamená to automaticky nelétatelné počasí.</p>")
    else:
        parts.append("<div style='font-size:16px;font-weight:bold;margin:10px 0 7px'>Přehled</div>")
        for day in sorted(by_day):
            day_id=f"day-{day:%Y%m%d}"
            parts.append(f"<div style='background:#eaf1f6;padding:7px 9px;font-size:13px;font-weight:bold;margin-top:9px'>{cz_day(day)}</div>")
            parts.append("<table role='presentation' cellpadding='0' cellspacing='0' style='width:100%;border-collapse:collapse'>")
            for name,start,end,m in sorted(by_day[day],key=lambda x:x[1]):
                key=f"w-{day:%Y%m%d}-{start:%H%M}-{len(parts)}"
                # A same-message anchor is useful in many email clients; some may ignore it.
                parts.append("<tr><td style='padding:6px 7px;border-bottom:1px solid #e7ecf1;font-size:13px'>")
                parts.append(f"<a href='#{key}' style='color:#173f63;text-decoration:underline'>{esc(name)}</a></td>")
                parts.append(f"<td style='padding:6px 7px;text-align:right;white-space:nowrap;border-bottom:1px solid #e7ecf1;font-size:13px'><b>{fmt_time(start)}–{fmt_time(end)}</b></td></tr>")
                # Retain stable link id for details by storing it alongside the matching row.
                m["_anchor"]=key
            parts.append("</table>")
        parts.append("<div style='font-size:16px;font-weight:bold;margin:18px 0 8px'>Detaily</div>")
        for day in sorted(by_day):
            parts.append(f"<div style='font-size:13px;font-weight:bold;color:#3c5570;margin:14px 0 5px'>{cz_day(day)}</div>")
            for name,start,end,m in sorted(by_day[day],key=lambda x:x[1]):
                wind=display_range(m["wind_speed_10m"]," m/s")
                gust=display_range(m["wind_gusts_10m"]," m/s")
                direction=display_range(m["wind_direction_10m"],"°",0)
                upper=display_range(m["wind_speed_80m"]," m/s")
                cloud=display_range(m["cloud_cover"]," %",0)
                low=display_range(m["cloud_cover_low"]," %",0)
                rain=display_range(m["precipitation_probability"]," %",0)
                parts.append(f"<table id='{m['_anchor']}' role='presentation' cellpadding='0' cellspacing='0' style='width:100%;border:1px solid #dce5ec;border-collapse:separate;margin:6px 0 8px'>")
                parts.append(f"<tr><td colspan='2' style='background:#f0f5f9;padding:7px 10px;font-size:14px'><b>{esc(name)}</b><span style='float:right'>{fmt_time(start)}–{fmt_time(end)}</span></td></tr>")
                parts.append(f"<tr><td style='padding:7px 10px 3px;font-size:13px;width:50%;vertical-align:top'>Vítr <b>{wind}</b><br><span style='color:#63758a'>Odkud {direction}</span></td><td style='padding:7px 10px 3px;font-size:13px;vertical-align:top'>Nárazy <b>{gust}</b><br><span style='color:#63758a'>80 m: {upper}</span></td></tr>")
                parts.append(f"<tr><td colspan='2' style='padding:3px 10px 9px;font-size:12px;color:#586b80'>Oblačnost {cloud} (nízká {low}) · srážky {rain}</td></tr></table>")
    if errors:
        parts.append("<div style='padding:9px;background:#fff1e9;border-left:3px solid #d36a36;margin-top:12px;font-size:12px'><b>Chyby dat</b><br>")
        parts.append("<br>".join(esc(e) for e in errors)+"</div>")
    parts.append("<div style='font-size:11px;line-height:1.5;color:#657789;margin-top:14px;padding-top:9px;border-top:1px solid #dbe4ed'>")
    parts.append("Kandidát podle modelu ≠ bezpečný let. Jen mezi východem a západem slunce, min. 60 minut. "
                 "Vítr 10/80 m není měření na startu; rotory, fronty a termika/XC nejsou spolehlivě posouzeny.")
    parts.append("</div></td></tr></table></body></html>")
    return "".join(parts)

def main():
    now=datetime.now(TZ)
    from pathlib import Path
    cache_path=Path("forecast_cache.json")
    if not cache_path.exists():
        raise RuntimeError("Missing verified forecast cache; email not sent")
    entries=json.loads(cache_path.read_text(encoding="utf-8"))
    cached={(entry["lat"],entry["lon"]):entry["data"] for entry in entries}
    model_data={(entry["lat"],entry["lon"]):entry["models"] for entry in entries}
    from preferences import load, excluded
    prefs=load()
    by_day=defaultdict(list)
    for site in SITES:
        name,lat,lon,*_=site
        data=cached[(lat,lon)]
        groups,_=consensus_windows(site,data,model_data[(lat,lon)],now)
        for group in groups:
            start,end=group[0][0],group[-1][1]
            if excluded(prefs,start.date().isoformat(),name): continue
            by_day[start.date()].append((name,start,end))
    count=sum(len(rows) for rows in by_day.values())
    url="https://jmkozel.github.io/paragliding-weather/"
    sender=os.getenv("SMTP_USER")
    password=os.getenv("SMTP_APP_PASSWORD")
    if not sender or not password:
        print("Email NOT sent: configure SMTP_USER and SMTP_APP_PASSWORD secrets.")
        return
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=os.getenv("REPORT_TO","jmkozel@gmail.com")
    msg["Subject"]=f"🪂 Letová okna | {now:%d.%m.%Y} | {count} kandidátů"
    lines=[f"🪂 LETOVÁ OKNA | {now:%d.%m.%Y}",f"{count} kandidátních oken během 5 dní",""]
    blocks=["<html><body style='margin:0;padding:12px;background:#f2f6fa;font-family:Arial,sans-serif;color:#203044'>",
            "<div style='max-width:620px;margin:auto;background:white'>",
            "<div style='background:#193652;color:white;padding:15px;font-size:19px;font-weight:bold'>🪂 Letová okna · 5 dní</div>",
            f"<div style='padding:14px'><p style='color:#64768a;font-size:13px'>{now:%d.%m.%Y} · {count} kandidátních oken</p>"]
    if by_day:
        for day in sorted(by_day):
            heading=cz_day(day)
            lines.extend([heading])
            blocks.append(f"<div style='background:#eaf1f6;padding:8px;font-size:14px;font-weight:bold;margin-top:12px'>{html.escape(heading)}</div>")
            blocks.append("<table role='presentation' style='width:100%;border-collapse:collapse'>")
            for name,start,end in sorted(by_day[day],key=lambda x:x[1]):
                hours=f"{fmt_time(start)}–{fmt_time(end)}"
                lines.append(f"  {name}: {hours}")
                blocks.append(f"<tr><td style='padding:7px 5px;border-bottom:1px solid #e8edf2;font-size:14px'>{html.escape(name)}</td><td style='text-align:right;white-space:nowrap;padding:7px 5px;border-bottom:1px solid #e8edf2;font-size:14px'><b>{hours}</b></td></tr>")
            blocks.append("</table>")
            lines.append("")
    else:
        lines.append("Žádné kandidátní okno podle dostupného modelu.")
        blocks.append("<p>Žádné kandidátní okno podle dostupného modelu.</p>")
    lines.extend(["","Podrobnosti a aktuální výhled: "+url,
                  "Kandidát není potvrzení bezpečných podmínek."])
    blocks.append(f"<p style='margin:20px 0'><a href='{url}' style='display:inline-block;background:#205c84;color:white;text-decoration:none;padding:11px 15px;border-radius:6px;font-weight:bold'>Zobrazit podrobná letová okna</a></p>")
    blocks.append("<p style='font-size:12px;color:#66788b'>Automatický modelový screening, nikoli potvrzení bezpečného letu.</p></div></div></body></html>")
    msg.set_content("\n".join(lines))
    msg.add_alternative("".join(blocks),subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(sender,password)
        smtp.send_message(msg)
    print("Email sent.")

if __name__=="__main__":
    main()
