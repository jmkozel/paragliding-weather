"""Generate public, read-only static paragliding dashboard. No private data."""
import html
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from preferences import load, excluded
from pwa_assets import build as build_pwa_assets
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
              <div class="choices"><button type="button" class="watch">☆ Sledovat</button><button type="button" class="exclude">Nemůžu</button><button type="button" class="exclude-day" title="Skrýt všechna letová okna v tento den, včetně nově přidaných">Nemůžu celý den</button></div>
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
    site_limits={s[0]:{'min':s[3],'max':s[4],'gust':s[5],'directions':s[6]} for s in SITES}
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
                               'low_cloud':data['cloud_cover_low'][i],
                               'cape':data['cape'][i],
                               'visibility':data['visibility'][i],
                               'wind80_direction':data['wind_direction_80m'][i],
                               'precipitation':data['precipitation'][i],
                               'rain':data['precipitation_probability'][i],
                               'screening':reason if not valid else 'Základní filtry splněny',
                               'consensus':status,
                               'models':[{'model':r['model'],'wind':r['wind'],'gust':r['gust'],'direction':r['direction'],'rain':r['rain'],'pass':r['pass']} for r in rows]})
            tracked.append({'day':day,'site':site,'key':key,'hourly':hourly,
                            'baseline':email_baselines.get(key,{}).get('snapshot'),
                            'limits':site_limits[site],
                            'items':[dict(w,trend=changes(dict(exists=True,day=day,site=site,start=w['start'],end=w['end'],m=w['m'],risks=w['notes'],logistics=w['logistics']),email_baselines.get(key,{}).get('snapshot'))) for d,ws in by_day.items() if d.isoformat()==day for w in ws if w['name']==site]})
    for d,items in by_day.items():
        for w in items:
            key=d.isoformat()+'|'+w['name']+'|'+w['start']
            base=next(x for x in tracked if x['key']==d.isoformat()+'|'+w['name'])
            tracked.append(dict(base,key=key,items=[dict(w,trend=changes(dict(exists=True,day=d.isoformat(),site=w['name'],start=w['start'],end=w['end'],m=w['m'],risks=w['notes'],logistics=w['logistics']),email_baselines.get(key,{}).get('snapshot')))],baseline=email_baselines.get(key,{}).get('snapshot')))
    # Persist detail for disappeared start-time windows as well.
    existing_keys={entry['key'] for entry in tracked}
    for key,action in prefs['windows'].items():
        if action!='watch' or key in existing_keys:continue
        parts=key.split('|')
        if len(parts)!=3:continue
        day,site,start=parts
        base=next((x for x in tracked if x['key']==day+'|'+site),None)
        if base:
            tracked.append(dict(base,key=key,items=[],baseline=email_baselines.get(key,{}).get('snapshot')))
    errorblock=('<section class="warning"><b>Chyby dat</b><p>'+ '<br>'.join(esc(x) for x in errors)+'</p></section>') if errors else ''
    empty='<p class="empty">V modelu nejsou nalezena kandidátní okna ≥ 60 minut. Neznamená to automaticky nelétatelné počasí.</p>' if not count else ''
    doc=f"""<!doctype html><html lang="cs"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Letová okna | Paragliding</title>
    <meta name="theme-color" content="#193652">
    <link rel="manifest" href="manifest.webmanifest">
    <link rel="icon" type="image/png" href="icon-192.png">
    <link rel="apple-touch-icon" href="icon-192.png">
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
    .choices{{flex-wrap:wrap}}.choices .exclude-day{{border-color:#d0b8a5;color:#77543b}}
    .risks{{margin:8px 0;padding:9px;background:#fff4e9;border-radius:6px;color:#684a30}}
    .risks.muted{{background:#f0f4f7;color:#526779}}
    .push-settings{{background:white;border-radius:10px;padding:14px;margin-bottom:16px;font-size:13px}}
    .push-settings p{{color:#61758a}}
    .tracked-report{{background:#fff;border:1px solid #d9e4ee;border-radius:13px;overflow:hidden;margin:12px 0 20px;box-shadow:0 2px 6px #dce5ee66}}
    .report-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:19px 20px 14px}}
    .eyebrow{{font-size:10px;font-weight:700;letter-spacing:.9px;color:#6c8397}}
    .report-time{{font-size:28px;font-weight:750;margin:5px 0 9px}}
    .flight-type{{display:inline-block;padding:5px 9px;border-radius:6px;background:#e7f1ec;color:#21634b;font-size:12px;font-weight:700}}
    .report-note{{max-width:520px;color:#687d8e;font-size:12px;line-height:1.5;margin:9px 0 0}}
    .depart-box{{background:#e9f1f7;border-radius:9px;padding:12px 16px;text-align:center;min-width:195px}}
    .depart-box small{{display:block;color:#60798e;font-size:10px;font-weight:700;letter-spacing:.4px}}
    .depart-box strong{{display:block;color:#1c537b;font-size:28px;margin-top:4px}}
    .depart-route{{display:block;margin-top:6px;color:#52728a;font-size:11px;line-height:1.45;font-weight:400;max-width:280px}}
    .direction-hint{{display:block;font-size:11px;color:#678095;margin-top:5px;line-height:1.4}}
    .cancel-alert{{background:#fff0ef;border-left:4px solid #c72d3a;border-radius:10px;padding:16px 18px;margin:14px 0;color:#922b34}}
    .cancel-alert strong{{display:block;font-size:20px;margin-bottom:7px}}
    .cancel-alert ul{{margin:6px 0;padding-left:18px;line-height:1.6;font-size:13px}}
    .model-matrix{{overflow-x:auto;max-width:100%;border:1px solid #dbe5ee;border-radius:9px;margin-top:10px}}
    .model-matrix table{{border-collapse:collapse;white-space:nowrap;width:100%;font-size:12px}}
    .model-matrix th,.model-matrix td{{border-bottom:1px solid #e5edf3;padding:9px 10px;text-align:center}}
    .model-matrix th:first-child,.model-matrix td:first-child{{position:sticky;left:0;background:#f3f7fb;text-align:left;font-weight:700;z-index:1}}
    .model-matrix th{{background:#eaf1f6;color:#47667c}}
    .model-matrix td.model-pass{{background:#eef8f1;color:#26694b}}
    .model-matrix td.model-fail{{background:#fff4f1;color:#9b4936}}
    .report-metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid #e6edf2;border-bottom:1px solid #e6edf2}}
    .metric-cell{{padding:14px 16px;border-right:1px solid #e6edf2;border-bottom:1px solid #e6edf2}}
    .metric-cell small{{display:block;font-size:11px;color:#688095;margin-bottom:6px}}
    .metric-cell strong{{font-size:16px;white-space:nowrap}}
    .report-foot{{padding:10px 20px 15px;font-size:13px;line-height:1.55}}
    .report-foot p{{margin:9px 0}}
    .compact-models{{padding:9px 0;border:0}}
    .compact-models p{{margin:5px 0}}
    .hour-table td.reason{{text-align:left;white-space:nowrap;font-size:12px}}
    .hour-table .hour-ok{{color:#26714b}}
    .hour-table .hour-no{{color:#a04e30}}
    .hour-table tr.in-window{{background:#f0f7f3}}
    @media(max-width:650px){{.report-top{{flex-direction:column}}.depart-box{{width:100%;text-align:left}}.report-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.metric-cell strong{{font-size:15px}}}}
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
    <main><p id="hidden-info" class="muted-note" role="status" aria-live="polite" style="display:none"></p><nav id="tracked-nav" aria-label="Sledovaná okna"></nav><section id="tracked-detail" hidden></section><div id="overview">
    <div class="grid">{''.join(cards)}</div>{empty}{errorblock}
    <details><summary>Spravovat skryté dny a okna</summary><div id="restore-list"></div></details></div>
    <section class="push-settings"><b>🔔 Mobilní notifikace</b><p id="push-status">Kontroluji dostupnost…</p><button id="push-enable" hidden>Zapnout notifikace</button><button id="push-disable" hidden>Vypnout notifikace</button></section>
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
        const original=d?.baseline?.exists?d.baseline:null;
        const startHint=selected.split("|")[2]||original?.start||"";
        const hourMinutes=t=>{{const p=t.split(":").map(Number);return p[0]*60+p[1];}};
        const relevant=(d?.hourly||[]).filter(h=>{{
          if(!startHint)return true;
          const t=hourMinutes(h.time),start=hourMinutes(startHint);
          const end=original?.end?hourMinutes(original.end):start+180;
          return t>=Math.floor(start/60)*60&&t<Math.max(end,start+60);
        }});
        const evaluate=h=>{{
          const reasons=[];
          if(!d?.limits)return [h.screening||"Neznámé podmínky"];
          const l=d.limits,w=h.wind,g=h.gust,dir=h.direction;
          if(w==null||g==null||dir==null)reasons.push("Chybí data o větru");
          else{{
            if(w<l.min)reasons.push("Slabý vítr "+w.toFixed(1)+" m/s (min. "+l.min+")");
            if(w>l.max)reasons.push("Silný vítr "+w.toFixed(1)+" m/s (max. "+l.max+")");
            if(g>l.gust)reasons.push("Nárazy "+g.toFixed(1)+" m/s (max. "+l.gust+")");
            if(!l.directions.some(r=>dir>=r[0]&&dir<=r[1]))reasons.push("Směr "+dir.toFixed(0)+"° mimo létatelný rozsah "+l.directions.map(r=>r.join("–")+"°").join(", "));
          }}
          if(h.upper!=null&&h.wind!=null&&(h.upper>12||h.upper-h.wind>7))reasons.push("Silný vítr v 80 m: "+h.upper.toFixed(1)+" m/s");
          if(h.precipitation>0.1)reasons.push("Předpověď srážek "+h.precipitation.toFixed(1)+" mm");
          if(h.rain>=60)reasons.push("Pravděpodobnost srážek "+h.rain.toFixed(0)+" %");
          if(h.visibility!=null&&h.visibility<5000)reasons.push("Nízká dohlednost "+Math.round(h.visibility)+" m");
          if(h.cape>=500)reasons.push("Zvýšená konvekce (CAPE "+Math.round(h.cape)+")");
          const passed=h.models.filter(m=>m.pass).length;
          if(h.consensus!=="good")reasons.push("Shoda jen "+passed+"/4 modelů");
          if(!reasons.length&&h.screening!=="Základní filtry splněny")reasons.push(h.screening);
          return reasons;
        }};
        if(!d||!d.items.length){{
          if(!d){{const p=document.createElement("p");p.textContent="Pro tento den nejsou dostupná aktuální data. Sledování pokračuje.";panel.appendChild(p);}}
          else{{
            const alert=document.createElement("div");alert.className="cancel-alert";
            const title=document.createElement("strong");title.textContent="❌ Sledované letové okno zaniklo";alert.appendChild(title);
            const intro=document.createElement("p");intro.textContent=original?"Původní okno "+original.start+"–"+original.end+" už nesplňuje nastavené limity.":"Původní okno od "+(startHint||"neznámého času")+" už není mezi vyhovujícími okny. Původní hodnoty nejsou uložené, proto nelze určit jejich přesnou změnu.";alert.appendChild(intro);
            const reasonMap=new Map();
            for(const h of relevant)for(const reason of evaluate(h)){{const label=reason.replace(/ [0-9]+(?:\\.[0-9]+)?(?:°| m\/s| mm| %| m)?(?: \\(.*)?$/,"");reasonMap.set(label,reason);}}
            const reasons=[...reasonMap.values()];
            const ul=document.createElement("ul");
            for(const reason of reasons.slice(0,7)){{const li=document.createElement("li");li.textContent=reason;ul.appendChild(li);}}
            if(!reasons.length){{const li=document.createElement("li");li.textContent="V aktuálním modelu není dostatečně dlouhý souvislý úsek splňující všechna kritéria.";ul.appendChild(li);}}
            alert.appendChild(ul);panel.appendChild(alert);
            if(original){{
              const oldBox=document.createElement("div");oldBox.className="tracked-report";
              const oldTitle=document.createElement("div");oldTitle.className="report-top";oldTitle.textContent="Poslední odeslaná předpověď · "+original.start+"–"+original.end;oldBox.appendChild(oldTitle);
              const oldMetrics=document.createElement("div");oldMetrics.className="report-metrics";
              for(const [label,key,unit] of [["Vítr 10 m","wind_speed_10m"," m/s"],["Nárazy","wind_gusts_10m"," m/s"],["Směr větru","wind_direction_10m","°"],["Vítr 80 m","wind_speed_80m"," m/s"],["Oblačnost","cloud_cover"," %"],["Nízká oblačnost","cloud_cover_low"," %"],["Pravd. srážek","precipitation_probability"," %"]]){{
                const cell=document.createElement("div");cell.className="metric-cell";
                const lbl=document.createElement("small");lbl.textContent=label;cell.appendChild(lbl);
                const v=document.createElement("strong");v.textContent=Array.isArray(original.m?.[key])?original.m[key].map(x=>Number(x).toFixed(1)).join("–")+unit:"–";cell.appendChild(v);
                if(key==="wind_direction_10m"&&d.limits){{const hint=document.createElement("span");hint.className="direction-hint";hint.textContent="Létatelný směr: "+d.limits.directions.map(r=>r.join("–")+"°").join(", ");cell.appendChild(hint);}}
                oldMetrics.appendChild(cell);
              }}
              oldBox.appendChild(oldMetrics);
              const log=document.createElement("div");log.className="depart-box";log.style.margin="14px";
              log.innerHTML="<small>PŮVODNĚ PLÁNOVANÝ ODJEZD</small>";
              const time=document.createElement("strong");time.textContent=original.logistics?.departure||"–";log.appendChild(time);
              const route=document.createElement("span");route.className="depart-route";route.textContent=(original.logistics?.drive_min??"–")+" min autem · příjezd "+(original.logistics?.arrival||"–")+" · "+(original.logistics?.prepare_min??"–")+" min příprava";log.appendChild(route);
              oldBox.appendChild(log);panel.appendChild(oldBox);
            }}
          }}
        }}
        else for(const w of d.items){{
          const box=document.createElement("article");box.className="tracked-report";
          const fmt=(v,unit="")=>v==null?"–":Number(v).toFixed(1)+unit;
          const range=(key,unit="")=>{{const v=w.m[key];return Array.isArray(v)?v.map(n=>fmt(n)).join("–")+unit:"–";}};
          const top=document.createElement("div");top.className="report-top";
          const left=document.createElement("div");left.innerHTML="<span class='eyebrow'>PŘEDPOVÍDANÉ LETOVÉ OKNO</span>";
          const time=document.createElement("div");time.className="report-time";time.textContent=w.start+"–"+w.end;left.appendChild(time);
          const type=document.createElement("span");type.className="flight-type";type.textContent="Svahové létání · podmíněně";left.appendChild(type);
          const typeNote=document.createElement("p");typeNote.className="report-note";typeNote.textContent="Směr a síla větru odpovídají filtrům pro daný svah. Termika a XC nejsou spolehlivě vyhodnoceny.";left.appendChild(typeNote);top.appendChild(left);
          const depart=document.createElement("div");depart.className="depart-box";
          const cap=document.createElement("small");cap.textContent="ODJEZD Z ČERNOŠIC";depart.appendChild(cap);
          const big=document.createElement("strong");big.textContent=w.logistics.departure;depart.appendChild(big);
          const route=document.createElement("span");route.className="depart-route";
          route.textContent=w.logistics.drive_min+" min autem · příjezd "+w.logistics.arrival+" · "+w.logistics.prepare_min+" min přesun a příprava · start "+w.start;depart.appendChild(route);top.appendChild(depart);box.appendChild(top);
          const metrics=document.createElement("div");metrics.className="report-metrics";
          for(const [label,key,unit] of [["Vítr 10 m","wind_speed_10m"," m/s"],["Nárazy","wind_gusts_10m"," m/s"],["Směr větru","wind_direction_10m","°"],["Vítr 80 m","wind_speed_80m"," m/s"],["Oblačnost","cloud_cover"," %"],["Nízká oblačnost","cloud_cover_low"," %"],["Pravd. srážek","precipitation_probability"," %"]]){{
            const cell=document.createElement("div");cell.className="metric-cell";
            const labelEl=document.createElement("small");labelEl.textContent=label;cell.appendChild(labelEl);
            const value=document.createElement("strong");value.textContent=range(key,unit);cell.appendChild(value);
            if(key==="wind_direction_10m"&&d?.limits){{const hint=document.createElement("span");hint.className="direction-hint";hint.textContent="Létatelný směr: "+d.limits.directions.map(r=>r[0]+"–"+r[1]+"°").join(", ");cell.appendChild(hint);}}
            metrics.appendChild(cell);
          }}
          box.appendChild(metrics);
          const foot=document.createElement("div");foot.className="report-foot";
          const risk=document.createElement("p");risk.innerHTML="<b>Rizika:</b> ";risk.appendChild(document.createTextNode(w.notes.join("; ")||"Bez dalších varovných signálů v hodnocených ukazatelích"));foot.appendChild(risk);
          const trend=document.createElement("p");trend.innerHTML="<b>Vývoj od posledního e-mailu:</b> ";trend.appendChild(document.createTextNode(w.trend?.join("; ")||"Bez změny"));foot.appendChild(trend);
          box.appendChild(foot);panel.appendChild(box);
        }}
        if(d?.baseline){{const b=document.createElement("p");b.className="hour-legend";b.textContent=d.baseline.exists?"Poslední odeslaný report: okno "+d.baseline.start+"–"+d.baseline.end+", odjezd "+d.baseline.logistics.departure:"Poslední odeslaný report: bez kandidátního okna";panel.appendChild(b);}}
        if(d?.hourly?.length){{
          const fmt=(v,unit="")=>v==null?"–":Number(v).toFixed(1)+unit;
          const daylight=d.hourly.filter(x=>Number(x.time.slice(0,2))>=7&&Number(x.time.slice(0,2))<=17);
          const hours=daylight.length?daylight:d.hourly;
          const heading=document.createElement("h3");heading.textContent="Předpověď po hodinách";panel.appendChild(heading);
          const legend=document.createElement("p");legend.className="hour-legend";legend.textContent="Vítr a nárazy v m/s, směr odkud ve stupních. Tabulku lze na mobilu posouvat vodorovně.";panel.appendChild(legend);
          const wrap=document.createElement("div");wrap.className="hour-table-wrap";
          const table=document.createElement("table");table.className="hour-table";
          const head=document.createElement("thead"),tr=document.createElement("tr");
          for(const label of ["Čas","Vítr","Nárazy","Směr","80 m","Oblač.","Nízká","Srážky","Shoda","Hodnocení"]){{const th=document.createElement("th");th.textContent=label;tr.appendChild(th);}}
          head.appendChild(tr);table.appendChild(head);
          const body=document.createElement("tbody");
          const shortReason=hour=>{{
            const raw=(hour.screening||"").toLowerCase();
            if(raw.includes("směr"))return "Špatný směr";
            if(raw.includes("vítr/nárazy")){{
              if(hour.wind!=null&&hour.wind<2)return "Slabý vítr";
              if(hour.gust!=null&&hour.wind!=null&&hour.gust>hour.wind*2.5)return "Silné nárazy";
              return "Vítr mimo limit";
            }}
            if(raw.includes("80 m"))return "Silný výškový vítr";
            if(raw.includes("konvektivní"))return "Konvekce";
            if(raw.includes("pravděpodobnost"))return "Riziko deště";
            if(raw.includes("srážky")||raw.includes("počasí"))return "Déšť / dohlednost";
            if(raw.includes("chybí"))return "Chybí data";
            if(hour.consensus!=="good")return "Neshoda modelů";
            return "Vyhovuje";
          }};
          for(const hour of hours){{
            const row=document.createElement("tr");
            const reason=shortReason(hour),good=reason==="Vyhovuje";
            if(good)row.className="in-window";
            const vals=[hour.time,fmt(hour.wind),fmt(hour.gust),fmt(hour.direction,"°"),fmt(hour.upper),fmt(hour.cloud,"%"),fmt(hour.low_cloud,"%"),fmt(hour.rain,"%"),hour.consensus==="good"?"3–4 ✓":hour.consensus==="uncertain"?"Nejistá":"Ne",reason];
            vals.forEach((v,i)=>{{const cell=document.createElement("td");cell.textContent=v;
              if(i===8)cell.className=hour.consensus==="good"?"hour-good":"hour-bad";
              if(i===9)cell.className="reason "+(good?"hour-ok":"hour-no");
              row.appendChild(cell);}});
            body.appendChild(row);
          }}
          table.appendChild(body);wrap.appendChild(table);panel.appendChild(wrap);
          const note=document.createElement("p");note.className="hour-legend";note.textContent="Hodnocení uvádí hlavní důvod vyřazení, ne všechny souběžné důvody. Shoda modelů sama o sobě nepotvrzuje bezpečné podmínky.";panel.appendChild(note);
          const details=document.createElement("details");details.className="hour-detail";
          const summary=document.createElement("summary");summary.textContent="Modely po hodinách · porovnání jako na Windy";details.appendChild(summary);
          const inner=document.createElement("div");inner.className="inner";
          const explain=document.createElement("p");explain.className="hour-legend";explain.textContent="Řádky = modely, sloupce = hodiny. V buňce je vítr / nárazy (m/s). Zelená = model splňuje limity, červená = nesplňuje. Tabulku lze posouvat do stran.";inner.appendChild(explain);
          const matrix=document.createElement("div");matrix.className="model-matrix";
          const mt=document.createElement("table"),mh=document.createElement("thead"),header=document.createElement("tr");
          for(const label of ["Model",...hours.map(h=>h.time)]){{const th=document.createElement("th");th.textContent=label;header.appendChild(th);}}
          mh.appendChild(header);mt.appendChild(mh);
          const mb=document.createElement("tbody");
          const modelNames=[...new Set(hours.flatMap(h=>h.models.map(m=>m.model)))];
          for(const name of modelNames){{
            const tr=document.createElement("tr"),th=document.createElement("td");th.textContent=name;tr.appendChild(th);
            for(const hour of hours){{
              const m=hour.models.find(x=>x.model===name),td=document.createElement("td");
              td.textContent=m?(fmt(m.wind)+" / "+fmt(m.gust)):"–";
              td.className=m?.pass?"model-pass":"model-fail";
              if(m)td.title="Směr "+fmt(m.direction,"°")+" · srážky "+fmt(m.rain," mm");
              tr.appendChild(td);
            }}
            mb.appendChild(tr);
          }}
          mt.appendChild(mb);matrix.appendChild(mt);inner.appendChild(matrix);
          details.appendChild(inner);panel.appendChild(details);
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
        card.querySelector('.exclude-day').onclick=()=>change(day,'*','exclude');
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
      const PUSH_URL='https://paragliding-push.jmkozel.workers.dev';
      const VAPID_KEY={json.dumps(os.environ.get("VAPID_PUBLIC_KEY",""))};
      const status=document.getElementById('push-status'),enable=document.getElementById('push-enable'),disable=document.getElementById('push-disable');
      const bytes=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4)),c=>c.charCodeAt(0));
      async function refreshPush(){{
        if(!VAPID_KEY){{status.textContent='Notifikace čekají na dokončení nastavení serveru.';return;}}
        if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){{status.textContent='Prohlížeč nepodporuje push notifikace.';return;}}
        try{{const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();status.textContent=sub?'Notifikace jsou zapnuté.':'Notifikace jsou vypnuté.';enable.hidden=!!sub;disable.hidden=!sub;}}
        catch(e){{status.textContent='Chyba: '+e.message;}}
      }}
      enable.onclick=async()=>{{
        enable.disabled=true;
        try{{
          if(await Notification.requestPermission()!=='granted')throw Error('Notifikace nejsou povolené');
          const reg=await navigator.serviceWorker.ready;
          const sub=await reg.pushManager.subscribe({{userVisibleOnly:true,applicationServerKey:bytes(VAPID_KEY)}});
          const r=await fetch(PUSH_URL+'/subscriptions',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{subscription:sub.toJSON()}})}});
          if(!r.ok){{await sub.unsubscribe();throw Error('Registrace na serveru: HTTP '+r.status);}}
          await refreshPush();
        }}catch(e){{status.textContent='Registrace selhala: '+e.message;}}
        finally{{enable.disabled=false;}}
      }};
      disable.onclick=async()=>{{
        disable.disabled=true;
        try{{
          const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();
          if(sub){{
            const r=await fetch(PUSH_URL+'/subscriptions',{{method:'DELETE',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{subscription:sub.toJSON()}})}});
            if(!r.ok)throw Error('Odhlášení na serveru selhalo');
            await sub.unsubscribe();
          }}
          await refreshPush();
        }}catch(e){{status.textContent='Odhlášení selhalo: '+e.message;}}
        finally{{disable.disabled=false;}}
      }};
      render();sync();
      if("serviceWorker" in navigator){{navigator.serviceWorker.register("./sw.js").then(refreshPush).catch(err=>console.warn("PWA worker:",err));}}
    }})();
    </script></body></html>"""
    out=Path("public");out.mkdir(exist_ok=True)
    (out/"index.html").write_text(doc,encoding="utf-8")
    (out/".nojekyll").write_text("",encoding="utf-8")
    build_pwa_assets()
    print(f"Generated {count} windows, {len(errors)} errors, public/index.html")

if __name__=="__main__":build()
