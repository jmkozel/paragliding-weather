"""Morning delivery, including a truthful alert when fresh weather data is unavailable."""
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

def alert(reason):
    sender=os.environ.get("SMTP_USER")
    password=os.environ.get("SMTP_APP_PASSWORD")
    if not sender or not password:
        raise RuntimeError("SMTP_USER or SMTP_APP_PASSWORD secret is missing")
    now=datetime.now(ZoneInfo("Europe/Prague"))
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=os.environ.get("REPORT_TO","jmkozel@gmail.com")
    msg["Subject"]=f"🪂 Předpověď nedostupná | {now:%d.%m.%Y}"
    msg.set_content(
        f"🪂 PARAGLIDING | {now:%d.%m.%Y}\n\n"
        "Dnešní automatické vyhodnocení nebylo dokončeno kvůli nedostupným datům "
        "nebo chybě generování. Nejde o potvrzení nulového počtu letových oken.\n\n"
        "Poslední zveřejněný web může být zastaralý:\n"
        "https://jmkozel.github.io/paragliding-weather/\n\n"
        "Podrobnosti chyby najdeš v GitHub Actions. "
        "Předpověď není záruka bezpečnosti letu.\n"
    )
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(sender,password)
        smtp.send_message(msg)
    print("Unavailable-data alert sent.")

def main():
    if Path("forecast_cache.json").exists():
        import forecast
        try:
            forecast.main()
            return
        except Exception as exc:
            print(f"Normal report failed: {type(exc).__name__}: {exc}")
            raise
    alert("missing forecast cache")

if __name__=="__main__":
    main()
