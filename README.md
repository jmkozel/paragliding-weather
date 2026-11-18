# Paragliding weather (pilot)

Automatic five-day preliminary forecast for Cukrák, Staňkovka and Raná via Open-Meteo.

## Email setup
The workflow runs near 07:00 Europe/Prague. To enable email delivery, create GitHub Actions repository secrets:
- `SMTP_USER`: sending Gmail address
- `SMTP_APP_PASSWORD`: Google app password, **not** your normal Gmail password.

Go to Settings → Secrets and variables → Actions → New repository secret.
Then go to Actions → Daily paragliding forecast → Run workflow and inspect logs.
Recipient is configured as jmkozel@gmail.com.

**Never share passwords in chat or commit them to this repository.**

## Limitations
Pilot only covers Cukrák, Staňkovka, Raná JV and SZ. The 10m wind model is only a preliminary screening, not a flight safety verdict. Check actual launch observations, winds aloft, rotor, clouds, fronts, and turbulence. GitHub scheduled workflows may be delayed. No email is sent until the secrets are set.
