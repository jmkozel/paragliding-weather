"""Generate public, read-only static paragliding dashboard. No private data."""
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from preferences import load, excluded
from urllib.parse import quote
from forecast import SITES, fetch_all_sites, fetch_model_comparison, consensus_windows, metrics, risk_notes, cz_day, display_range

def build():
    now=datetime.now(ZoneInfo("Europe/Prague"))
    prefs=load()
    by_day=defaultdict(list); cache=fetch_all_sites(); comparison=fetch_model_comparison(); errors=[]
    for site in SITES:
        name,lat,lon,*_=site
        try:
            key=(lat,lon)
            if key not in cache: raise ValueError('Missing location in batch response')
            groups,consensus=consensus_windows(site,cache[key],comparison[key],now)
            for group in groups:
                by_day[group[0][0].date()].append({
                    "name":name,"start":group[0][0].strftime("%H:%M"),
                    "end":group[-1][1].strftime("%H:%M"),
                    "m":metrics(cache[key],group),"notes":risk_notes(cache[key],group),
                    "models":[{"model":name,"wind":min(r["wind"] for r in [consensus[i][1][j] for i in [part[2] for part in group]]),
                               "gust":max(r["gust"] for r in [consensus[i][1][j] for i in [part[2] for part in group]])}
                              for j,name in enumerate(comparison[key])],
                    "lat":lat,"lon":lon})
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    if errors:
        raise RuntimeError('Incomplete weather data: '+ '; '.join(errors))
    Path('forecast_cache.json').write_text(json.dumps([{'lat':lat,'lon':lon,'data':data,'models':comparison[(lat,lon)]} for (lat,lon),data in cache.items()]),encoding='utf-8')
    esc=html.escape
    days=sorted(by_day)
    controls="".join(f'<button class="filter" data-day="{day.isoformat()}">{esc(cz_day(day))}</button>' for day in days)
    cards=[]
    for day in days:
        for item in sorted(by_day[day],key=lambda x:x["start"]):
            m=item["m"]
            def metric(key,unit="",digits=1):return esc(display_range(m[key],unit,digits))
            windy=f'https://www.windy.com/{item["lat"]:.3f}/{item["lon"]:.3f}?{item["lat"]:.3f},{item["lon"]:.3f},11'
            window_key=f'{day.isoformat()}|{item["name"]}'
            is_excluded=excluded(prefs,day.isoformat(),item["name"])
            is_watched=prefs["windows"].get(window_key)=="watch"
            notes=item["notes"]
            model_table="<div class='risks muted'><b>Modely: vítr / max. náraz (m/s)</b><br>"+ "<br>".join(f"{esc(row['model'])}: {row['wind']:.1f} / {row['gust']:.1f}" for row in item["models"])+"</div>"
            risk_html=("<div class='risks'><b>Na co dát pozor:</b> "+ "; ".join(esc(x) for x in notes)+"</div>") if notes else "<div class='risks muted'>Bez dodatečných varovných signálů v těchto dílčích ukazatelích. Nejde o potvrzení bezpečnosti.</div>"
            cards.append(f"""<article class="window" data-day="{day.isoformat()}" data-key="{esc(window_key,quote=True)}" data-shared="{'excluded' if is_excluded else ('watch' if is_watched else '')}">
              <div class="head"><div><span class="day">{esc(cz_day(day))}</span><h2>{esc(item["name"])}</h2></div>
              <strong class="time">{item["start"]}–{item["end"]}</strong></div>
              <div class="numbers"><div><small>Vítr · odkud {metric("wind_direction_10m","°",0)}</small><b>{metric("wind_speed_10m"," m/s")}</b></div>
              <div><small>Nárazy</small><b>{metric("wind_gusts_10m"," m/s")}</b></div></div>
              <div class="choices"><button type="button" class="watch">☆ Sledovat</button><button type="button" class="exclude">Nemůžu</button></div>
              <details><summary>Podrobnosti a kontrola před letem</summary>
              <div class="detail">Vítr 80 m: <b>{metric("wind_speed_80m"," m/s")}</b><br>
              Oblačnost: <b>{metric("cloud_cover"," %",0)}</b> · nízká: {metric("cloud_cover_low"," %",0)}<br>
              Pravděpodobnost srážek: <b>{metric("precipitation_probability"," %",0)}</b></div>
              {risk_html}{model_table}
              <a href="{windy}" target="_blank" rel="noopener noreferrer">Ověřit předpověď na Windy ↗</a>
              </details></article>""")
    count=len(cards)
    tracked=[]
    for key,action in prefs['windows'].items():
        if action=='watch':
            day,site=key.split('|',1)
            tracked.append({'day':day,'site':site,'key':key,'items':[w for d,ws in by_day.items() if d.isoformat()==day for w in ws if w['name']==site]})
    errorblock=('<section class="warning"><b>Chyby dat</b><p>'+ '<br>'.join(esc(x) for x in errors)+'</p></section>') if errors else ''
    empty='<p class="empty">V modelu nejsou nalezena kandidátní okna ≥ 60 minut. Neznamená to automaticky nelétatelné počasí.</p>' if not count else ''
    doc=f"""<!doctype html><html lang="cs"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Letová okna | Paragliding</title>
    <style>
    :root{{font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;color:#1e344a;background:#f2f6fa}}
    *{{box-sizing:border-box}}body{{margin:0}}header{{background:#193652;color:#fff;padding:22px max(18px,calc((100% - 950px)/2))}}
    h1{{margin:5px 0;font-size:clamp(25px,5vw,36px)}}header p{{margin:5px 0;color:#d2e1ef;font-size:14px}}
    main{{max-width:950px;margin:auto;padding:18px}}.summary{{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px}}
    .summary span{{background:white;padding:10px 14px;border-radius:9px;box-shadow:0 1px 3px #d6e1eb}}
    nav{{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}}button{{border:1px solid #b8cbda;background:#fff;color:#1e405d;border-radius:20px;padding:8px 13px;cursor:pointer;font-size:13px}}
    button.active{{background:#1c537b;color:#fff;border-color:#1c537b}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:12px}}
    .window{{background:white;border:1px solid #dae4ed;border-radius:11px;overflow:hidden;box-shadow:0 2px 5px #dae4ed66}}
    .head{{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;background:#eaf1f6}}
    .day{{font-size:12px;color:#61768a}}h2{{margin:3px 0 0;font-size:19px}}.time{{white-space:nowrap;font-size:17px}}
    .numbers{{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:13px 14px}}
    .numbers small{{display:block;color:#5c7184;font-size:12px;margin-bottom:4px}}.numbers b{{font-size:17px}}
    details{{border-top:1px solid #e5edf3;padding:9px 14px 13px;font-size:13px}}summary{{cursor:pointer;color:#205b85;font-weight:600}}
    .detail{{line-height:1.9;padding:10px 0}}a{{color:#175c90}}.warning{{background:#fff0e7;padding:13px;border-radius:8px;margin:14px 0}}
    footer{{color:#60758a;font-size:12px;line-height:1.6;margin-top:22px;padding:15px 0;border-top:1px solid #d9e3ed}}
    .empty{{background:#fff;padding:20px;border-radius:9px}}
    .choices{{display:flex;gap:8px;padding:0 14px 11px}}
    .choices button{{font-size:12px;border:1px solid #b8cbda;padding:8px 12px;border-radius:7px}}
    .choices button[aria-pressed="true"]{{background:#204d70;color:white}}
    .risks{{margin:8px 0;padding:9px;background:#fff4e9;border-radius:6px;color:#684a30}}
    .risks.muted{{background:#f0f4f7;color:#526779}}
    .window[hidden]{{display:none!important}}
    .muted-note{{font-size:12px;color:#63758a;line-height:1.5;margin:10px 0}}
    </style></head><body><header><div style="font-size:12px;letter-spacing:1px">🪂 PARAGLIDING</div>
    <h1>Letová okna</h1><p>Výhled na 5 dní · aktualizováno {now:%d.%m.%Y v %H:%M} (Praha)</p></header>
    <main><nav id="tracked-nav" aria-label="Sledovaná okna"></nav><section id="tracked-detail" hidden></section><div id="overview"><div class="summary"><span><b>{count}</b> podrobných letových oken</span><span><b>{len(days)}</b> dní s okny</span><span><b>{len(SITES)-len(errors)}/{len(SITES)}</b> vyhodnocených sektorů</span></div>
    <p class="muted-note">V hlavním přehledu jsou pouze okna, kde alespoň 3 ze 4 modelů splňují místní limity a žádný neukazuje výrazný exces. Navíc platí základní meteorologické filtry. Modely nejsou nezávislé a jejich shoda nezaručuje bezpečný let.</p>
    <p class="muted-note">Rozhodnutí ukládáš jedním kliknutím. Skryté možnosti lze obnovit níže.</p>
    <nav aria-label="Filtrovat podle dne"><button class="filter active" data-day="all">Všechny dny</button>{controls}</nav>
    <div id="day-actions"></div><p id="hidden-info" class="muted-note"></p>
    <div class="grid">{''.join(cards)}</div>{empty}{errorblock}
    <details><summary>Spravovat skryté dny a okna</summary><div id="restore-list"></div></details></div>
    <footer><b>Bezpečnost:</b> Kandidátní okno je automatický screening, nikoli doporučení ke startu.
    Vždy ověř aktuální měření, výškový vítr, rotory, fronty a místní podmínky.
    Modelový vítr 10 m/80 m není měření na startovišti. Termika a XC nejsou spolehlivě vyhodnoceny.
    Volby se ukládají přes Cloudflare KV. Sledované detaily se aktualizují s webem.</footer></main>
    <script>
    (()=>{{
      const API='https://paragliding-control.jmkozel.workers.dev/preferences';
      const cards=[...document.querySelectorAll('.window')];
      const filters=[...document.querySelectorAll('.filter')];
      const info=document.getElementById('hidden-info');
      let active='all',busy=false;
      let days={json.dumps(prefs["days"],ensure_ascii=False)};
      let windows={json.dumps(prefs["windows"],ensure_ascii=False)};
      const trackedData={json.dumps(tracked,ensure_ascii=False)};
      let selected="overview";
      function renderTracked(){{
        const nav=document.getElementById("tracked-nav"),panel=document.getElementById("tracked-detail");nav.replaceChildren();panel.replaceChildren();
        const entries=Object.entries(windows).filter(([k,v])=>v==="watch").sort();
        const button=(label,key)=>{{const b=document.createElement("button");b.textContent=label;b.classList.toggle("active",selected===key);b.onclick=()=>{{selected=key;renderTracked();}};nav.appendChild(b);}};
        button("Přehled","overview");
        for(const [key] of entries){{const d=trackedData.find(x=>x.key===key);const [day,site]=key.split("|");const times=d?.items?.[0]?d.items[0].start+"–"+d.items[0].end:"bez okna";button(day.slice(8)+"."+day.slice(5,7)+" "+site+" "+times,key);}}
        if(selected!=="overview"&&!entries.some(([k])=>k===selected))selected="overview";
        const show=selected!=="overview";document.getElementById("overview").hidden=show;panel.hidden=!show;
        if(!show)return;
        const d=trackedData.find(x=>x.key===selected),heading=document.createElement("h2");heading.textContent=selected.replace("|"," · ");panel.appendChild(heading);
        if(!d||!d.items.length){{const p=document.createElement("p");p.textContent="Aktuálně bez kandidátního okna. Předpověď se mohla změnit.";panel.appendChild(p);}}
        else for(const w of d.items){{const box=document.createElement("article");box.className="window";box.style.padding="15px";const h=document.createElement("h3");h.textContent=w.start+"–"+w.end;box.appendChild(h);
          for(const [k,label,unit] of [["wind_speed_10m","Vítr"," m/s"],["wind_gusts_10m","Nárazy"," m/s"],["wind_direction_10m","Směr","°"],["wind_speed_80m","Vítr 80 m"," m/s"],["cloud_cover","Oblačnost"," %"],["precipitation_probability","Srážky"," %"]]){{const p=document.createElement("p");const a=w.m[k];p.textContent=label+": "+(a?a.map(x=>Number(x).toFixed(1)).join("–")+unit:"bez dat");box.appendChild(p);}}
          const p=document.createElement("p");p.textContent="Rizika: "+(w.notes.join("; ")||"bez dodatečných signálů");box.appendChild(p);
          const m=document.createElement("p");m.textContent="Modely: "+w.models.map(x=>x.model+" "+x.wind.toFixed(1)+"/"+x.gust.toFixed(1)+" m/s").join(" · ");box.appendChild(m);panel.appendChild(box);}}
        const stop=document.createElement("button");stop.textContent="Přestat sledovat";stop.onclick=()=>{{const [day,site]=selected.split("|");selected="overview";change(day,site,"clear");}};panel.appendChild(stop);
      }}
      function render(){{
        filters.forEach(b=>b.classList.toggle('active',b.dataset.day===active));
        cards.forEach(card=>{{
          const k=card.dataset.key;
          card.hidden=!!days[card.dataset.day]||windows[k]==='exclude'||(active!=='all'&&card.dataset.day!==active);
          const watch=card.querySelector('.watch');
          watch.textContent=windows[k]==='watch'?'★ Sledováno · zrušit':'☆ Sledovat';
          watch.setAttribute('aria-pressed',String(windows[k]==='watch'));
        }});
        const area=document.getElementById('day-actions');
        area.replaceChildren();
        if(active!=='all'){{
          const button=document.createElement('button');
          button.textContent=days[active]?'Obnovit celý den':'Nemůžu celý den';
          button.onclick=()=>change(active,'*',days[active]?'clear':'exclude');
          area.appendChild(button);
        }}
        const restore=document.getElementById('restore-list');
        restore.replaceChildren();
        for(const [day,value] of Object.entries(days)){{
          if(!value)continue;
          const button=document.createElement('button');
          button.textContent='Obnovit celý den: '+day;
          button.onclick=()=>change(day,'*','clear');
          restore.appendChild(button);
        }}
        for(const [k,value] of Object.entries(windows)){{
          if(value!=='exclude')continue;
          const pos=k.indexOf('|');
          if(pos<0)continue;
          const button=document.createElement('button');
          button.textContent='Obnovit '+k.slice(pos+1)+' ('+k.slice(0,pos)+')';
          button.onclick=()=>change(k.slice(0,pos),k.slice(pos+1),'clear');
          restore.appendChild(button);
        }}
        info.textContent=cards.filter(card=>days[card.dataset.day]||windows[card.dataset.key]==='exclude').length+' skrytých oken';
        renderTracked();
      }}
      async function change(day,site,action){{
        if(busy)return;
        busy=true;
        info.textContent='Ukládám…';
        try{{
          const response=await fetch(API,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{day,site,action}})}});
          if(!response.ok)throw Error('HTTP '+response.status);
          if(site==='*'){{if(action==='clear')delete days[day];else days[day]=true;}}
          else{{const k=day+'|'+site;if(action==='clear')delete windows[k];else windows[k]=action;}}
          render();
        }}catch(e){{info.textContent='Uložení selhalo: '+e.message;}}
        finally{{busy=false;}}
      }}
      cards.forEach(card=>{{
        const pos=card.dataset.key.indexOf('|');
        const day=card.dataset.key.slice(0,pos),site=card.dataset.key.slice(pos+1);
        card.querySelector('.watch').onclick=()=>change(day,site,windows[card.dataset.key]==='watch'?'clear':'watch');
        card.querySelector('.exclude').onclick=()=>change(day,site,'exclude');
      }});
      filters.forEach(b=>b.onclick=()=>{{active=b.dataset.day;render();}});
      async function sync(){{
        try{{
          const response=await fetch(API,{{cache:'no-store'}});
          if(!response.ok)throw Error('HTTP '+response.status);
          const data=await response.json();
          if(!data.complete)throw Error('Neúplná data');
          days={{}};windows={{}};
          for(const item of data.preferences){{
            const pos=item.key.indexOf('|');
            if(pos<0)continue;
            const day=item.key.slice(0,pos),site=item.key.slice(pos+1);
            if(site==='*'&&item.value==='exclude')days[day]=true;
            else if(site!=='*'&&['watch','exclude'].includes(item.value))windows[item.key]=item.value;
          }}
          render();
        }}catch(e){{info.textContent='Nepodařilo se načíst rozhodnutí: '+e.message;}}
      }}
      render();sync();
    }})();
    </script></body></html>"""
    out=Path("public");out.mkdir(exist_ok=True)
    (out/"index.html").write_text(doc,encoding="utf-8")
    (out/".nojekyll").write_text("",encoding="utf-8")
    print(f"Generated {count} windows, {len(errors)} errors, public/index.html")

if __name__=="__main__":build()
