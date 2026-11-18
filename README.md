# Paragliding Weather | denní e-mail

Automatický pětidenni screening všech 13 sektorů (11 místních terénů) podle uživatelských limitů větru a nárazů.

## Co se vyhodnocuje
- Cukrák, Staňkovka, Karlík, Řevničov, Suchomasty/Klonk, Raná JV/SZ, Jeviněves, Říp JV/JZ/SZ, Koukolova hora, Beroun/vysílač.
- Hodinová data Open-Meteo: 10m vítr a nárazy, 80m vítr, směr, srážky, pravděpodobnost srážek, dohlednost, meteorologické kódy, oblačnost a CAPE.
- Jen místní interval od východu do západu slunce. Částečné hodiny se ořezávají; okno musí mít alespoň 60 minut souvisle.
- Konzervativní doplňkové filtry: 80m vítr nejvýše 12 m/s a rozdíl vůči 10m větru nejvýše 7 m/s, CAPE pod 500 J/kg (je-li dostupné), pravděpodobnost srážek pod 60 % (je-li dostupná).
- Přehled pouze dnů s kandidátními okny, pak meteorologické podrobnosti; chyby dat se hlásí samostatně.

## Automatické odesílání
GitHub Actions plánuje běh kolem 07:00 Europe/Prague. GitHub může spuštění opozdit.
Příjemce: jmkozel@gmail.com.

Repository secrets v Settings → Secrets and variables → Actions:
- `SMTP_USER`: Gmail účet odesílatele
- `SMTP_APP_PASSWORD`: heslo aplikace Google, nikoli běžné heslo.

Ruční test: Actions → Daily paragliding forecast → Run workflow → main → Run workflow.
Po dokončení zkontroluj příchozí poštu a případně GitHub Actions logs.

## Bezpečnostní omezení
**Kandidátní okno není doporučení ke startu.** Modelový vítr 10 m/80 m není měření na startu ani vertikální profil nad startem. Přibližné souřadnice některých lokalit vyžadují ověření. Místní turbulence, rotory, fronty, aktuální měření a vývoj termiky nelze tímto filtrem bezpečně posoudit. Termika/XC se proto nehodnotí číselně. Nejsou-li dostupná data, není to vyhodnoceno jako nevhodné počasí.

Další práce: ověřit souřadnice všech startovišť, zkontrolovat s Windy a stanicemi, přidat robustnější vertikální profil, oblačnou základnu, frontální situaci a přehlednější HTML šablonu.
