"""Felles testdata (tall fra spesifikasjonen, kap. 2)."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

OSLO = timezone(timedelta(hours=1))

SEP = {
    "id": "2026-09",
    "start": "2026-08-30",
    "slutt": "2026-10-01",
    "leilighet_kwh": 228.0,
    "hus_kwh": 2156.64,
    "kraft": 4028.93,
    "nettleie": 1655.32,
    "norgespris": 2819.94,
    "sum": 2864.31,
    "snitt": 1.3280,
    "belop": 302.79,
    "forfall": "2026-10-15",
    "status": "betalt",
    "generert": "2026-10-03T08:00:00+02:00",
    "epost_sendt": None,
    "epost_ventende_siden": None,
    "kilde": "import",
    "notat": "",
}

OKT = {
    "id": "2026-10",
    "start": "2026-10-01",
    "slutt": "2026-11-01",
    "leilighet_kwh": 234.0,
    "hus_kwh": 2402.13,
    "kraft": 4635.08,
    "nettleie": 1786.72,
    "norgespris": 3298.51,
    "sum": 3123.30,
    "snitt": 1.3002,
    "belop": 304.25,
    "forfall": "2026-11-15",
    "status": "ikke_betalt",
    "generert": "2026-11-03T08:11:00+01:00",
    "epost_sendt": None,
    "epost_ventende_siden": None,
    "kilde": "import",
    "notat": "",
}

LEIETAKER = {
    "navn": "Kari Nordmann",
    "epost": "kari@example.com",
    "adresse": "Testveien 1, 1. etasje",
    "innflyttet": "2026-08-30",
}

UTLEIER = {
    "navn": "Ola Utleier",
    "epost": "ola@example.com",
    "kontonummer": "1234.56.78903",
}


def perioder():
    return [deepcopy(SEP), deepcopy(OKT)]


def side_ctx(**over):
    ctx = {
        "leietaker": LEIETAKER,
        "utleier": UTLEIER,
        "forfallsdag": 15,
        "perioder": perioder(),
        "hittil": {"kwh": 21.85, "snitt": 3.1434, "kr": 68.4},
        "estimat": {"kwh": 285.48, "kr": 371.18},
        "oppdatert": datetime(2026, 11, 3, 17, 20, tzinfo=OSLO),
    }
    ctx.update(over)
    return ctx


# --- konfigurasjon og kilder for koordinatortester ---------------------------

CFG = {
    "leietaker_navn": LEIETAKER["navn"],
    "leietaker_epost": LEIETAKER["epost"],
    "adresse": LEIETAKER["adresse"],
    "innflyttet": LEIETAKER["innflyttet"],
    "utleier_navn": UTLEIER["navn"],
    "utleier_epost": UTLEIER["epost"],
    "kontonummer": UTLEIER["kontonummer"],
    "forfallsdag": 15,
    "ent_regnskap": "sensor.jarvis_stromregnskap",
    "ent_utility": "sensor.leilighet_strom_denne_maneden",
    "ent_import": "sensor.minusmaler_leilighet_import",
    "ent_effekt": "sensor.minusmaler_leilighet_effekt",
    "ent_prognose": "sensor.mal_forbruk_prognose",
    "varsel_tjeneste": "notify.varsle_magnar",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_bruker": "ola@example.com",
    "smtp_passord": "app-passord-test",
    "cc_utleier": True,
    "slug": "testslug123",
    "publiser_side": True,
    "snitt_min": 0.5,
    "snitt_maks": 3.0,
    "endring_maks_prosent": 60.0,
    "kjoredag": 3,
    "kjoretid": "08:00:00",
    "siste_sjekkdag": 6,
    "importer_historikk": False,
    "maaler_start_stand": 0.0,
    "kopi_til_utleier": False,
}

# SYNTETISKE testtall for november (ikke ekte data).
NOV_HUS = {
    "mnd": "2026-11",
    "kwh": 2500.0,
    "kraft": 4700.0,
    "nettleie": 1800.0,
    "kapasitet": 525,
    "fast": 25,
    "norgespris": 3400.0,
    "sum": 3100.0,
    "snitt": 1.24,
    "leilighet_kwh": 250.0,
    "leilighet_kr": 310.0,
}

# Slik de to første månedene ser ut i sensoren (form hentet fra den levende sensoren).
SEP_HUS = {
    "mnd": "2026-09", "kwh": 2156.64, "kraft": 4028.93, "nettleie": 1655.32,
    "kapasitet": 525, "fast": 25, "norgespris": 2819.94, "sum": 2864.31,
    "snitt": 1.3281, "leilighet_kwh": 228, "leilighet_kr": 302.79,
}  # fmt: skip
OKT_HUS = {
    "mnd": "2026-10", "kwh": 2402.13, "kraft": 4635.08, "nettleie": 1786.72,
    "kapasitet": 525, "fast": 25, "norgespris": 3298.51, "sum": 3123.3,
    "snitt": 1.3002, "leilighet_kwh": 234, "leilighet_kr": 304.25,
}  # fmt: skip

DENNE_DES = {
    "mnd": "2026-12", "kwh": 50.0, "kraft": 150.0, "nettleie": 120.0, "kapasitet": 525,
    "fast": 25, "norgespris": 100.0, "sum": 170.0, "snitt": 3.4, "leilighet_kwh": 5.0,
    "leilighet_kr": 17.0,
}  # fmt: skip


def sett_kilder(
    hass,
    *,
    maneder=None,
    denne=None,
    utility="21.85",
    last_period="250.0",
    endring=22,
):
    """Setter tilstanden til de eksterne sensorene som integrasjonen leser."""
    hass.states.async_set(
        "sensor.jarvis_stromregnskap",
        "2026-11",
        {
            "maneder": maneder if maneder is not None else [SEP_HUS, OKT_HUS, NOV_HUS],
            "denne_maneden": denne if denne is not None else DENNE_DES,
        },
    )
    hass.states.async_set(
        "sensor.leilighet_strom_denne_maneden",
        utility,
        {"last_period": last_period, "unit_of_measurement": "kWh"},
    )
    hass.states.async_set("sensor.minusmaler_leilighet_import", utility, {})
    hass.states.async_set("sensor.minusmaler_leilighet_effekt", "850", {})
    hass.states.async_set(
        "sensor.mal_forbruk_prognose",
        "2941",
        {"endring_prosent": endring, "forrige_maned": 2402, "hittil": 268},
    )


# Målerstand ved månedsskiftene (kWh): novembers forbruk blir 250,0 kWh.
MAALERSTANDER = {
    "2026-11-01": {"stand": 0.0, "kilde": "start", "tid": "2026-11-03T20:16:00+01:00"},
    "2026-12-01": {"stand": 250.0, "kilde": "live", "tid": "2026-12-01T00:00:20+01:00"},
}
