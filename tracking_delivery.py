"""Tracked-window email monitoring. Baselines advance only after SMTP delivery."""
import base64
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from forecast import SITES, fetch_all_sites, fetch_model_comparison, consensus_windows, metrics, risk_notes, display_range
from logistics import departure
from preferences import load

TZ=ZoneInfo("Europe/Prague")
REPO="jmkozel/paragliding-weather"
STATE_PATH="tracking_state.json"
PAGE="https://jmkozel.github.io/paragliding-weather/"
FIELDS=(("wind_speed_10m","Vítr"," m/s"),("wind_gusts_10m","Nárazy"," m/s"),
        ("wind_direction_10m","Směr","°"),("wind_speed_80m","Vítr 80 m"," m/s"),
        ("cloud_cover","Oblačnost"," %"),("cloud_cover_low","Nízká oblačnost"," %"),
        ("precipitation_probability","Pravděpodobnost srážek"," %"))

def github(method="GET", body=None, sha=None):
    token=os.environ["GITHUB_TOKEN"]
    url="https://api.github.com/repos/"+REPO+"/contents/"+STATE_PATH
    payload=None
    if body is not None:
        data={"message":"Update tracked-window email baselines [skip ci]",
              "content":base64.b64encode(json.dumps(body,ensure_ascii=False,indent=2).encode()).decode()}
        if sha:data["sha"]=sha
        payload=json.dumps(data).encode()
    req=urllib.request.Request(url,data=payload,method=method,headers={
        "Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
        "User-Agent":"paragliding-tracking/1","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        if method=="GET" and exc.code==404:return None
        raise

def read_state():
    obj=github()
    if not obj:return {},None
    return json.loads(base64.b64decode(obj["content"])),obj["sha"]

def snapshot(site,day,now,cache,models):
    name,lat,lon,*_=site
    groups,_=consensus_windows(site,cache[(lat,lon)],models[(lat,lon)],now)
    matches=[g for g in groups if g[0][0].date().isoformat()==day]
    if not matches:return {"exists":False,"day":day,"site":name}
    # Prefer the longest available candidate interval.
    group=max(matches,key=lambda g:(g[-1][1]-g[0][0]).total_seconds())
    start,end=group[0][0].strftime("%H:%M"),group[-1][1].strftime("%H:%M")
    m=metrics(cache[(lat,lon)],group)
    return {"exists":True,"day":day,"site":name,"start":start,"end":end,
            "m":m,"risks":risk_notes(cache[(lat,lon)],group),
            "logistics":departure(name,day,start)}

def minutes(t):
    h,m=map(int,t.split(":"));return h*60+m

def delta_minutes(a,b):
    return minutes(a)-minutes(b)

def changes(new,old):
    if old is None:return ["Sledování zahájeno"]
    if new["exists"]!=old["exists"]:
        return ["Letové okno "+("znovu nalezeno" if new["exists"] else "zaniklo")]
    if not new["exists"]:return []
    result=[]
    for key,label in (("start","Začátek"),("end","Konec")):
        diff=delta_minutes(new[key],old[key])
        if diff:result.append(f"{label}: posun o {abs(diff)} min "+("později" if diff>0 else "dříve"))
    for key,label,unit in FIELDS:
        a=new["m"].get(key);b=old["m"].get(key)
        if a and b:
            d=round((sum(a)/len(a))-(sum(b)/len(b)),1)
            if abs(d)>=0.1:result.append(f"{label}: změna průměru {d:+.1f}{unit}")
    if set(new["risks"])!=set(old["risks"]):result.append("Změna rizik")
    return result

def significant(new,old):
    if old is None or new["exists"]!=old["exists"]:return True
    if not new["exists"]:return False
    if any(abs(delta_minutes(new[k],old[k]))>=30 for k in ("start","end")):return True
    if set(new["risks"])!=set(old["risks"]):return True
    for key,threshold in (("wind_speed_10m",0.8),("wind_gusts_10m",1.0),
                          ("wind_direction_10m",20),("wind_speed_80m",1.5),
                          ("precipitation_probability",15),("cloud_cover",20)):
        a=new["m"].get(key);b=old["m"].get(key)
        if a and b and abs(sum(a)/len(a)-sum(b)/len(b))>=threshold:return True
    return False

def phase(now,day,window):
    target=datetime.fromisoformat(day+"T"+(window.get("start","12:00"))).replace(tzinfo=TZ)
    departure_time=datetime.fromisoformat(day+"T"+window["logistics"]["departure"]).replace(tzinfo=TZ) if window.get("exists") else target-timedelta(hours=2)
    if now>=departure_time:return "done"
    if now>=target.replace(hour=0,minute=0)-timedelta(hours=6):return "changes"
    if target-now<=timedelta(days=2):return "three"
    return "daily"

def scheduled(now,mode,last):
    if last and last.date()==now.date() and mode=="daily":return False
    if mode=="daily":return now.hour==7
    if mode=="three":
        return now.hour in (7,12,18) and (not last or last.date()!=now.date() or last.hour!=now.hour)
    return False

def format_email(now,items):
    lines=[f"SLEDOVANÁ LETOVÁ OKNA · {now:%d.%m.%Y %H:%M}",""]
    for snap,old,reason in items:
        lines.append(snap["site"]+" · "+snap["day"]+" · "+reason)
        if not snap["exists"]:
            lines.append("Aktuálně bez kandidátního letového okna.")
        else:
            log=snap["logistics"]
            lines.extend([f"Okno: {snap['start']}–{snap['end']}",
                          f"Odjezd: {log['departure']} · autem {log['drive_min']} min · příjezd {log['arrival']} · přesun a příprava {log['prepare_min']} min"])
            for key,label,unit in FIELDS:
                current=display_range(snap["m"].get(key),unit)
                previous=old.get("m",{}).get(key) if old and old.get("exists") else None
                trend=""
                if previous and snap["m"].get(key):
                    a=snap["m"][key];d=round(sum(a)/len(a)-sum(previous)/len(previous),1)
                    if d:trend=f" ({d:+.1f}{unit} proti minulému e-mailu)"
                lines.append(f"{label}: {current}{trend}")
            lines.append("Rizika: "+("; ".join(snap["risks"]) if snap["risks"] else "bez dodatečných signálů"))
            if old and old.get("exists"):
                diff=delta_minutes(log["departure"],old["logistics"]["departure"])
                if diff:lines.append(f"Odjezd: o {abs(diff)} min "+("později" if diff>0 else "dříve"))
        changeset=changes(snap,old)
        if changeset:lines.append("VÝVOJ: "+"; ".join(changeset))
        lines.extend(["Detail: "+PAGE,""])
    lines.append("Automatický modelový screening není potvrzení bezpečných letových podmínek.")
    return "\n".join(lines)

def send(subject,body):
    user=os.environ["SMTP_USER"];password=os.environ["SMTP_APP_PASSWORD"]
    msg=EmailMessage();msg["From"]=user;msg["To"]=os.environ.get("REPORT_TO","jmkozel@gmail.com")
    msg["Subject"]=subject;msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(user,password);smtp.send_message(msg)

def main():
    now=datetime.now(TZ)
    prefs=load()
    watched={k for k,v in prefs["windows"].items() if v=="watch"}
    state,sha=read_state()
    state={k:v for k,v in state.items() if k in watched}
    if not watched:
        if sha:github("PUT",state,sha)
        print("No watched windows");return
    sites={s[0]:s for s in SITES}
    cache=fetch_all_sites();models=fetch_model_comparison()
    pending=[]
    for key in sorted(watched):
        try:
            day,name=key.split("|",1)
            if name not in sites:continue
            snap=snapshot(sites[name],day,now,cache,models)
            old_state=state.get(key,{})
            old=old_state.get("snapshot")
            last=datetime.fromisoformat(old_state["sent_at"]) if old_state.get("sent_at") else None
            mode=phase(now,day,snap if snap["exists"] else (old or snap))
            if mode=="done":continue
            if mode=="changes":
                if significant(snap,old):pending.append((key,snap,old,"Změna předpovědi"))
            elif scheduled(now,mode,last):
                pending.append((key,snap,old,"Pravidelný report"))
        except Exception as exc:
            print("Skipped invalid watch "+key+": "+str(exc))
    if not pending:
        print("No tracked emails due");return
    body=format_email(now,[(s,o,reason) for _,s,o,reason in pending])
    send(f"🪂 Sledovaná okna | {now:%d.%m. %H:%M} | {len(pending)}",body)
    # Only delivered emails become comparison baselines.
    for key,snap,_,_ in pending:state[key]={"snapshot":snap,"sent_at":now.isoformat()}
    github("PUT",state,sha)
    print(f"Sent {len(pending)} tracked-window updates and persisted baseline")

if __name__=="__main__":main()
