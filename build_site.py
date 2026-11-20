"""Generate public, read-only static paragliding dashboard. No private data."""
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from preferences import load, excluded
from logistics import departure
from tracking_delivery import read_state, changes
from urllib.parse import quote
from forecast import SITES, fetch_all_sites, fetch_model_comparison, consensus_windows, metrics, risk_notes, cz_day, display_range, screening, model_consensus

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
                    "lat":lat,"lon":lon,
                    "logistics":departure(name,group[0][0].date().isoformat(),group[0][0].strftime("%H:%M"))})
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
            window_key=f'{day.isoformat()}|{item["name"]}|{item["start"]}'
            is_excluded=excluded(prefs,day.isoformat(),item["name"]) or prefs["windows"].get(window_key)=="exclude"
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
    try:
        email_baselines,_=read_state()
    except Exception as exc:
        print('Email baseline unavailable for web trend: '+str(exc))
        email_baselines={}
    # Precompute details for every site/day, not only previously watched ones.
    # This allows immediate one-click watching without rebuilding the website.
    tracked=[]
    for site_config in SITES:
        site,lat,lon,*_=site_config
        loc=(lat,lon)
        data=cache[loc]['hourly']
        for day in dict.fromkeys(t[:10] for t in data['time']):
            key=day+'|'+site
            hourly=[]
            for i,t in enumerate(data['time']):
                if not t.startswith(day):continue
                # Only daytime hours are useful for launch screening.
                if not (7<=int(t[11:13])<=17):continue
                valid,reason=screening(site_config,data,i)
                status,rows=model_consensus(site_config,comparison[loc],t)
                hourly.append({'time':t[11:16],'wind':data['wind_speed_10m'][i],
                               'gust':data['wind_gusts_10m'][i],
                               'direction':data['wind_direction_10m'][i],
                               'upper':data['wind_speed_80m'][i],
                               'cloud':data['cloud_cover'][i],
                               'rain':data['precipitation_probability'][i],
                               'screening':reason if not valid else 'Základní filtry splněny',
                               'consensus':status,
                               'models':[{'model':r['model'],'wind':r['wind'],'gust':r['gust'],'pass':r['pass']} for r in rows]})
            tracked.append({'day':day,'site':site,'key':key,'hourly':hourly,
                            'baseline':email_baselines.get(key,{}).get('snapshot'),
                            'items':[dict(w,trend=changes(dict(exists=True,day=day,site=site,start=w['start'],end=w['end'],m=w['m'],risks=w['notes'],logistics=w['logistics']),email_baselines.get(key,{}).get('snapshot'))) for d,ws in by_day.items() if d.isoformat()==day for w in ws if w['name']==site]})
    for d,items in by_day.items():
        for w in items:
            key=d.isoformat()+'|'+w['name']+'|'+w['start']
            base=next(x for x in tracked if x['key']==d.isoformat()+'|'+w['name'])
            tracked.append(dict(base,key=key,items=[dict(w,trend=changes(dict(exists=True,day=d.isoformat(),site=w['name'],start=w['start'],end=w['end'],m=w['m'],risks=w['notes'],logistics=w['logistics']),email_baselines.get(key,{}).get('snapshot')))],baseline=email_baselines.get(key,{}).get('snapshot')))
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
    .tracked-heading{{font-size:22px;margin:12px 0 6px}}
    .tracked-sub{{font-size:13px;color:#64788b;margin:0 0 16px}}
    .tracked-status{{background:#fff;border-left:4px solid #cb9340;border-radius:8px;padding:13px 15px;margin:14px 0;line-height:1.5}}
    .tracked-summary{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:12px 0}}
    .tracked-summary div{{background:white;border-radius:9px;padding:12px}}
    .tracked-summary small{{display:block;color:#65798b;font-size:12px}}
    .tracked-summary b{{font-size:19px}}
    .hour-table-wrap{{overflow-x:auto;background:white;border-radius:10px;border:1px solid #dce5ec}}
    .hour-table{{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}}
    .hour-table th,.hour-table td{{padding:10px 9px;text-align:right;border-bottom:1px solid #e5edf3}}
    .hour-table th:first-child,.hour-table td:first-child{{text-align:left;position:sticky;left:0;background:white}}
    .hour-table th{{background:#eaf1f6;color:#536b7e;font-size:12px}}
    .hour-table tr:last-child td{{border-bottom:0}}
    .hour-table .hour-bad{{color:#9b542f}}
    .hour-table .hour-good{{color:#26714b}}
    .hour-detail{{margin:12px 0;background:white;border:1px solid #dae4ed;border-radius:10px;overflow:hidden}}
    .hour-detail summary{{padding:13px 14px;font-size:14px;list-style:auto}}
    .hour-detail .inner{{padding:0 14px 13px}}
    .model-row{{display:grid;grid-template-columns:1fr auto auto;gap:10px;padding:8px 0;border-bottom:1px solid #e5edf3;font-size:13px}}
    .model-row:last-child{{border-bottom:0}}
    .hour-legend{{font-size:12px;color:#61758a;margin:9px 0 16px;line-height:1.5}}
    @media(max-width:500px){{.hour-table th,.hour-table td{{padding:10px 7px}}}}
    .window[hidden],#overview[hidden],#tracked-detail[hidden]{{display:none!important}}
    .compact-count{{font-size:12px;color:#d2e1ef;margin:5px 0 0}}
    .muted-note{{font-size:12px;color:#63758a;line-height:1.5;margin:10px 0}}
    </style></head><body><header><div style="font-size:12px;letter-spacing:1px">🪂 PARAGLIDING</div>
    <h1>Letová okna</h1><p class="compact-count"><span id="compact-count"></span> · aktualizováno {now:%d.%m. %H:%M}</p></header>
    <main><nav id="tracked-nav" aria-label="Sledovaná okna"></nav><section id="tracked-detail" hidden></section><div id="overview">
    <div class="grid">{''.join(cards)}</div>{empty}{errorblock}
    <details><summary>Spravovat skryté dny a okna</summary><div id="restore-list"></div></details></div>
    <footer><p><b>Metodika:</b> V hlavním přehledu jsou pouze okna, kde alespoň 3 ze 4 modelů splňují místní limity a žádný neukazuje výrazný exces. Navíc platí základní meteorologické filtry. Modely nejsou nezávislé a jejich shoda nezaručuje bezpečný let.</p><b>Bezpečnost:</b> Kandidátní okno je automatický screening, nikoli doporučení ke startu.
    Vždy ověř aktuální měření, výškový vítr, rotory, fronty a místní podmínky.
    Modelový vítr 10 m/80 m není měření na startovišti. Termika a XC nejsou spolehlivě vyhodnoceny.
    Volby se ukládají přes Cloudflare KV. Sledované detaily se aktualizují s webem.</footer></main>
    <script>
    (()=>{{
      const API='https://paragliding-control.jmkozel.workers.dev/preferences';
      const cards=[...document.querySelectorAll('.window')];
      const filters=[];
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
        for(const [key] of entries){{const d=trackedData.find(x=>x.key===key);const [day,site]=key.split("|");button(day.slice(8)+"."+day.slice(5,7)+" "+site+(key.split("|")[2]?" "+key.split("|")[2]:"")+(d&&!d.items.length?" ❌":""),key);}}
        if(selected!=="overview"&&!entries.some(([k])=>k===selected))selected="overview";
        const show=selected!=="overview";document.getElementById("overview").hidden=show;panel.hidden=!show;
        if(!show)return;
        const d=trackedData.find(x=>x.key===selected),heading=document.createElement("h2");const [dateLabel,siteLabel]=selected.split("|");heading.className="tracked-heading";heading.textContent=siteLabel+" · "+dateLabel.slice(8)+"."+dateLabel.slice(5,7)+".";panel.appendChild(heading);
        const stop=document.createElement("button");stop.textContent="Přestat sledovat";stop.style.marginBottom="12px";stop.onclick=()=>{{const [day,...parts]=selected.split("|");selected="overview";change(day,parts.join("|"),"clear");}};panel.appendChild(stop);
        if(!d||!d.items.length){{const p=document.createElement("p");p.textContent=d?"Aktuálně bez vhodného kandidátního okna. Sledování pokračuje. Níže jsou předpovídané hodnoty a důvody vyřazení.":"Pro tento den zatím nejsou k dispozici data z poslední aktualizace. Sledování zůstává aktivní.";panel.appendChild(p);}}
        else for(const w of d.items){{const box=document.createElement("article");box.className="window";box.style.padding="15px";const h=document.createElement("h3");h.textContent=w.start+"–"+w.end;box.appendChild(h);
          for(const [k,label,unit] of [["wind_speed_10m","Vítr"," m/s"],["wind_gusts_10m","Nárazy"," m/s"],["wind_direction_10m","Směr","°"],["wind_speed_80m","Vítr 80 m"," m/s"],["cloud_cover","Oblačnost"," %"],["precipitation_probability","Srážky"," %"]]){{const p=document.createElement("p");const a=w.m[k];p.textContent=label+": "+(a?a.map(x=>Number(x).toFixed(1)).join("–")+unit:"bez dat");box.appendChild(p);}}
          const trend=document.createElement("p");trend.textContent="Vývoj od posledního e-mailu: "+(w.trend?.join("; ")||"bez změny");box.appendChild(trend);
          const log=w.logistics,route=document.createElement("div");route.className="risks muted";route.textContent="Odjezd z Černošic "+log.departure+" · "+log.drive_min+" min autem · příjezd "+log.arrival+" · "+log.prepare_min+" min přesun a příprava · připraven ke startu "+w.start;box.appendChild(route);
          const p=document.createElement("p");p.textContent="Rizika: "+(w.notes.join("; ")||"bez dodatečných signálů");box.appendChild(p);
          const m=document.createElement("p");m.textContent="Modely: "+w.models.map(x=>x.model+" "+x.wind.toFixed(1)+"/"+x.gust.toFixed(1)+" m/s").join(" · ");box.appendChild(m);panel.appendChild(box);}}
        if(d?.baseline){{const b=document.createElement("p");b.className="risks muted";b.textContent=d.baseline.exists?"Poslední odeslaný report: okno "+d.baseline.start+"–"+d.baseline.end+", plánovaný odjezd "+d.baseline.logistics.departure:"Poslední odeslaný report: bez kandidátního okna";panel.appendChild(b);}}
        if(d?.hourly?.length){{
          const fmt=(v,unit="")=>v==null?"–":Number(v).toFixed(1)+unit;
          const daylight=d.hourly.filter(x=>Number(x.time.slice(0,2))>=7&&Number(x.time.slice(0,2))<=17);
          const hours=daylight.length?daylight:d.hourly;
          const heading=document.createElement("h3");heading.textContent="Předpověď po hodinách";panel.appendChild(heading);
          const legend=document.createElement("p");legend.className="hour-legend";legend.textContent="Denní hodiny · vodorovným posunutím tabulky zobrazíš další údaje. Klepnutím na hodinu otevřeš podrobnosti a jednotlivé modely.";panel.appendChild(legend);
          const wrap=document.createElement("div");wrap.className="hour-table-wrap";
          const table=document.createElement("table");table.className="hour-table";
          const head=document.createElement("thead"),tr=document.createElement("tr");
          for(const label of ["Čas","Vítr","Nárazy","Směr","80 m","Oblač.","Srážky","Shoda"]){{const th=document.createElement("th");th.textContent=label;tr.appendChild(th);}}
          head.appendChild(tr);table.appendChild(head);
          const body=document.createElement("tbody");
          for(const hour of hours){{
            const row=document.createElement("tr");
            const vals=[hour.time,fmt(hour.wind),fmt(hour.gust),fmt(hour.direction,"°"),fmt(hour.upper),fmt(hour.cloud,"%"),fmt(hour.rain,"%"),hour.consensus==="good"?"3–4 ✓":hour.consensus==="uncertain"?"Nejistá":"Ne"];
            vals.forEach((v,i)=>{{const cell=document.createElement("td");cell.textContent=v;if(i===7)cell.className=hour.consensus==="good"?"hour-good":"hour-bad";row.appendChild(cell);}});
            body.appendChild(row);
          }}
          table.appendChild(body);wrap.appendChild(table);panel.appendChild(wrap);
          const units=document.createElement("p");units.className="hour-legend";units.textContent="Vítr, nárazy a 80 m v m/s · směr odkud ve stupních · oblačnost a pravděpodobnost srážek v %. Shoda označuje souhlas modelů, ne bezpečnost letu.";panel.appendChild(units);
          const detailTitle=document.createElement("h3");detailTitle.textContent="Proč jednotlivé hodiny nevyhovují";panel.appendChild(detailTitle);
          for(const hour of hours){{
            const detail=document.createElement("details");detail.className="hour-detail";
            const summary=document.createElement("summary");summary.textContent=hour.time+" · "+(hour.screening==="Základní filtry splněny"?(hour.consensus==="good"?"Splněné filtry":"Nedostatečná shoda modelů"):hour.screening);detail.appendChild(summary);
            const inner=document.createElement("div");inner.className="inner";
            const caption=document.createElement("p");caption.className="hour-legend";caption.textContent="Model · vítr / nárazy (m/s) · splňuje limity";inner.appendChild(caption);
            for(const m of hour.models){{const r=document.createElement("div");r.className="model-row";
              for(const value of [m.model,fmt(m.wind)+" / "+fmt(m.gust),m.pass?"✓ Ano":"× Ne"]){{const cell=document.createElement("span");cell.textContent=value;r.appendChild(cell);}}
              inner.appendChild(r);}}
            detail.appendChild(inner);panel.appendChild(detail);
          }}
        }}

      }}
      function render(){{
        filters.forEach(b=>b.classList.toggle('active',b.dataset.day===active));
        cards.forEach(card=>{{
          const k=card.dataset.key;
          card.hidden=!!days[card.dataset.day]||windows[k]==='exclude'||windows[k.slice(0,k.lastIndexOf('|'))]==='exclude';
          const watch=card.querySelector('.watch');
          watch.textContent=windows[k]==='watch'?'★ Sledováno · zrušit':'☆ Sledovat';
          watch.setAttribute('aria-pressed',String(windows[k]==='watch'));
        }});
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
        const hidden=cards.filter(card=>card.hidden).length;
        const watched=Object.values(windows).filter(v=>v==='watch').length;
        document.getElementById('compact-count').textContent=cards.length+' nalezených oken, z toho '+watched+' sledovaných a '+hidden+' skrytých';
        info.textContent='';
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
