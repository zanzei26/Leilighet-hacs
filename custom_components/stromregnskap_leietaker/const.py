"""Konstanter for Strømregnskap leietaker."""

from __future__ import annotations

DOMAIN = "stromregnskap_leietaker"

# --- nøkler i config entry (data) ---
CONF_LEIETAKER_NAVN = "leietaker_navn"
CONF_LEIETAKER_EPOST = "leietaker_epost"
CONF_ADRESSE = "adresse"
CONF_INNFLYTTET = "innflyttet"
CONF_UTLEIER_NAVN = "utleier_navn"
CONF_UTLEIER_EPOST = "utleier_epost"
CONF_KONTONUMMER = "kontonummer"
CONF_FORFALLSDAG = "forfallsdag"

CONF_ENT_REGNSKAP = "ent_regnskap"
CONF_ENT_UTILITY = "ent_utility"
CONF_ENT_IMPORT = "ent_import"
CONF_MAALER_START_STAND = "maaler_start_stand"
CONF_LADER_AKTIV = "lader_aktiv"
CONF_ENT_LADER = "ent_lader"
CONF_ENT_EFFEKT = "ent_effekt"
CONF_ENT_PROGNOSE = "ent_prognose"
CONF_VARSEL_TJENESTE = "varsel_tjeneste"

CONF_SMTP_HOST = "smtp_host"
CONF_SMTP_PORT = "smtp_port"
CONF_SMTP_BRUKER = "smtp_bruker"
CONF_SMTP_PASSORD = "smtp_passord"
CONF_CC_UTLEIER = "cc_utleier"
CONF_KOPI_TIL_UTLEIER = "kopi_til_utleier"
CONF_SEND_TEST = "send_test"

CONF_SLUG = "slug"
CONF_PUBLISER_SIDE = "publiser_side"

CONF_SNITT_MIN = "snitt_min"
CONF_SNITT_MAKS = "snitt_maks"
CONF_ENDRING_MAKS = "endring_maks_prosent"
CONF_KJOREDAG = "kjoredag"
CONF_KJORETID = "kjoretid"
CONF_SISTE_SJEKKDAG = "siste_sjekkdag"

CONF_IMPORTER_HISTORIKK = "importer_historikk"

# --- standardverdier (fra spesifikasjonen) ---
DEFAULT_ENT_REGNSKAP = "sensor.jarvis_stromregnskap"
DEFAULT_ENT_UTILITY = "sensor.leilighet_strom_denne_maneden"
DEFAULT_ENT_IMPORT = "sensor.minusmaler_leilighet_import"
DEFAULT_MAALER_START_STAND = 0.0
DEFAULT_ENT_EFFEKT = "sensor.minusmaler_leilighet_effekt"
DEFAULT_ENT_PROGNOSE = "sensor.mal_forbruk_prognose"
DEFAULT_VARSEL_TJENESTE = "notify.notify"

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587

DEFAULT_FORFALLSDAG = 15
DEFAULT_SNITT_MIN = 0.50
DEFAULT_SNITT_MAKS = 3.00
DEFAULT_ENDRING_MAKS = 60.0
DEFAULT_KJOREDAG = 3
DEFAULT_KJORETID = "08:00:00"
DEFAULT_SISTE_SJEKKDAG = 6

SLUG_LENGDE_BYTES = 18  # token_urlsafe(18) gir 24 tegn

OPPDATERINGSINTERVALL_TIMER = 1
EPOST_MAKS_TIMER = 48

# --- eksisterende historikk som kan importeres ved første oppsett (kap. 2) ---
# Tallene er hentet ordrett fra spesifikasjonen. «belop» er det faktisk fakturerte
# beløpet og beregnes ikke på nytt.
HISTORIKK = [
    {
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
    },
    {
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
    },
]
