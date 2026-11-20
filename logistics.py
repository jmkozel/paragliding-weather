"""User-specified travel and launch preparation times, in minutes."""
from datetime import datetime, timedelta

TIMES = {
    "Cukrák": (5,40),
    "Staňkovka": (5,40),
    "Karlík": (10,20),
    "Řevničov": (40,20),
    "Suchomasty / Klonk": (30,30),
    "Raná JV": (60,35),
    "Raná SZ": (60,35),
    "Jeviněves": (60,20),
    "Říp JV": (60,45),
    "Říp JZ": (60,45),
    "Říp SZ": (60,45),
    "Koukolova hora": (35,30),
    "Beroun / vysílač": (30,40),
}

def departure(site, day, start):
    drive, prepare = TIMES[site]
    beginning = datetime.fromisoformat(day + "T" + start)
    return {
        "drive_min": drive,
        "prepare_min": prepare,
        "departure": (beginning-timedelta(minutes=drive+prepare)).strftime("%H:%M"),
        "arrival": (beginning-timedelta(minutes=prepare)).strftime("%H:%M"),
    }
