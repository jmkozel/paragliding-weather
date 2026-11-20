"""Morning push summary from the already verified forecast cache.

Does not fetch weather again, and never claims that missing data means zero windows.
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from forecast import SITES, consensus_windows
from preferences import load, excluded
from push_delivery import deliver

def main():
    path=Path("forecast_cache.json")
    if not path.exists():
        print("Morning push skipped: no verified forecast cache")
        return
    now=datetime.now(ZoneInfo("Europe/Prague"))
    entries=json.loads(path.read_text(encoding="utf-8"))
    cached={(e["lat"],e["lon"]):e for e in entries}
    prefs=load()
    windows=[]
    for site in SITES:
        name,lat,lon,*_=site
        entry=cached.get((lat,lon))
        if not entry:
            raise RuntimeError(f"Missing forecast data for {name}")
        groups,_=consensus_windows(site,entry["data"],entry["models"],now)
        for group in groups:
            start,end=group[0][0],group[-1][1]
            if excluded(prefs,start.date().isoformat(),name):
                continue
            windows.append((start,name,end))
    windows.sort()
    count=len(windows)
    title=f"🪂 Ranní letová okna · {count} kandidátů"
    if windows:
        lines=[f"{name} {start:%d.%m. %H:%M}–{end:%H:%M}" for start,name,end in windows[:3]]
        body="; ".join(lines)
        if count>3:body+=f"; a dalších {count-3} v aplikaci"
    else:
        body="Podle aktuálního modelového screeningu nebylo nalezeno žádné kandidátní okno."
    deliver(title,body,tag="paragliding-morning-"+now.strftime("%Y%m%d"))

if __name__=="__main__":
    main()
