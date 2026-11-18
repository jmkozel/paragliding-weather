#!/usr/bin/env python3
"""Daily preliminary paragliding window report. Forecasts are NOT flight clearance."""
import json, os, smtplib, ssl, urllib.parse, urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Europe/Prague")
# Pilot sites: coordinates are approximate, not a substitute for local wind readings.
SITES=[
 {"name":"Cukrák","lat":49.9381,"lon":14.3354,"min":2,"max":8,"gust":10,"ranges":[(270,360)]},
 {"name":"Staňkovka","lat":49.9686,"lon":14.3251,"min":3,"max":8,"gust":10,"ranges":[(110,170)]},
 {"name":"Raná JV","lat":50.4065,"lon":13.7710,"min":2,"max":6,"gust":10,"ranges":[(70,190)]},
 {"name":"Raná SZ","lat":50.4065,"lon":13.7710,"min":2,"max":6,"gust":10,"ranges":[(250,360),(0,20)]},
]
FIELDS="wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,visibility,weather_code"
def fetch(lat,lon):
    args={"latitude":lat,"longitude":lon,"hourly":FIELDS,"wind_speed_unit":"ms",
          "timezone":"Europe/Prague","forecast_days":5}
    url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode(args)
    with urllib.request.urlopen(url,timeout=25) as r:
        return json.load(r)["hourly"]
def eligible(s,h,i):
    w=h["wind_speed_10m"][i]; g=h["wind_gusts_10m"][i]
    d=h["wind_direction_10m"][i]; p=h["precipitation"][i]
    v=h["visibility"][i]; code=h["weather_code"][i]
    if any(x is None for x in (w,g,d,p,v,code)): return False
    return (s["min"]<=w<=s["max"] and g<=s["gust"] and
            any(a<=d<=b for a,b in s["ranges"]) and p<=0.1 and
            v>=5000 and code not in (45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,99))
def windows(s,h):
    # Forecast time slots are one hour; >=1 hour is a candidate, not a safety verdict.
    result=[]; start=None
    n=len(h["time"])
    for i in range(n+1):
        good=i<n and eligible(s,h,i)
        if good and start is None: start=i
        if not good and start is not None:
            result.append((start,i))
            start=None
    return result
def main():
    now=datetime.now(TZ)
    lines=[f"Paragliding | předběžný výhled {now:%d.%m.%Y %H:%M} (Praha)",
           "Automatický screening modelu Open-Meteo, nikoli potvrzení bezpečných podmínek.",""]
    found=0; errors=[]
    cache={}
    for s in SITES:
        key=(s["lat"],s["lon"])
        try:
            if key not in cache: cache[key]=fetch(*key)
            h=cache[key]; wins=windows(s,h)
            if wins:
                lines.append(s["name"]+":")
                for a,b in wins:
                    begin=datetime.fromisoformat(h["time"][a])
                    end=datetime.fromisoformat(h["time"][b-1])+timedelta(hours=1)
                    lines.append(f"  {begin:%d.%m. %H:%M}–{end:%H:%M} | {b-a} h (kandidát)")
                    found+=1
            else: lines.append(s["name"]+": bez kandidátního okna podle filtru")
        except Exception as exc:
            errors.append(s["name"]+": "+str(exc))
    if errors:
        lines+=["","CHYBA ZÍSKÁNÍ DAT (nikoli špatné letové počasí):"]+errors
    if not found: lines+=["","Nenalezeno potvrzené okno. To neznamená, že létání není možné."]
    lines+=["","POZOR: Model 10m větru nezachytí lokální rotory, turbulenci, vítr na startu a ve výšce ani změny během letu.",
            "Před letem vždy zkontroluj aktuální měření, výškový vítr, oblačnost, srážky, fronty a místní podmínky.",
            "Pilotní verze sleduje jen Cukrák, Staňkovku a Ranou; další terény přidáme po ověření."]
    body="\n".join(lines)
    print(body)
    sender=os.getenv("SMTP_USER"); password=os.getenv("SMTP_APP_PASSWORD")
    recipient=os.getenv("REPORT_TO","jmkozel@gmail.com")
    if not sender or not password:
        print("\nEmail NOT sent: configure SMTP_USER and SMTP_APP_PASSWORD GitHub Actions secrets.")
        return
    msg=EmailMessage()
    msg["From"]=sender; msg["To"]=recipient
    msg["Subject"]=f"Paragliding: výhled {now:%d.%m.%Y}"
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(sender,password)
        smtp.send_message(msg)
    print("Email sent.")
if __name__=="__main__": main()
