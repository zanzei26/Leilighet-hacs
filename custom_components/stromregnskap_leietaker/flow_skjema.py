"""Skjemaer, validering og normalisering for oppsettsflyten og valgflyten."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .const import (
    CONF_ADRESSE,
    CONF_CC_UTLEIER,
    CONF_ENDRING_MAKS,
    CONF_ENT_EFFEKT,
    CONF_ENT_IMPORT,
    CONF_ENT_PROGNOSE,
    CONF_ENT_REGNSKAP,
    CONF_ENT_UTILITY,
    CONF_FORFALLSDAG,
    CONF_INNFLYTTET,
    CONF_KJOREDAG,
    CONF_KJORETID,
    CONF_KONTONUMMER,
    CONF_LEIETAKER_EPOST,
    CONF_LEIETAKER_NAVN,
    CONF_MAALER_START_STAND,
    CONF_PUBLISER_SIDE,
    CONF_SEND_TEST,
    CONF_SISTE_SJEKKDAG,
    CONF_SMTP_BRUKER,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSORD,
    CONF_SMTP_PORT,
    CONF_SNITT_MAKS,
    CONF_SNITT_MIN,
    CONF_UTLEIER_EPOST,
    CONF_UTLEIER_NAVN,
    CONF_VARSEL_TJENESTE,
    DEFAULT_ENDRING_MAKS,
    DEFAULT_ENT_EFFEKT,
    DEFAULT_ENT_IMPORT,
    DEFAULT_ENT_PROGNOSE,
    DEFAULT_ENT_REGNSKAP,
    DEFAULT_ENT_UTILITY,
    DEFAULT_FORFALLSDAG,
    DEFAULT_KJOREDAG,
    DEFAULT_KJORETID,
    DEFAULT_MAALER_START_STAND,
    DEFAULT_SISTE_SJEKKDAG,
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    DEFAULT_SNITT_MAKS,
    DEFAULT_SNITT_MIN,
    DEFAULT_VARSEL_TJENESTE,
    HISTORIKK,
)
from .page import fmt_tall

EPOST_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INGEN_LENKE = "(ingen ekstern adresse funnet ennå – sett ekstern URL eller slå på Nabu Casa)"


def _tekst(**kw: Any) -> TextSelector:
    return TextSelector(TextSelectorConfig(**kw))


def _tall(minimum: float, maksimum: float, steg: float = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maksimum, step=steg, mode=NumberSelectorMode.BOX)
    )


def _sensor() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="sensor"))


# --- skjemaer ---------------------------------------------------------------------------


def schema_leietaker(d: dict[str, Any], *, bare_leietaker: bool = False) -> vol.Schema:
    felt: dict[Any, Any] = {
        vol.Required(CONF_LEIETAKER_NAVN): _tekst(),
        vol.Required(CONF_LEIETAKER_EPOST): _tekst(type=TextSelectorType.EMAIL),
        vol.Required(CONF_ADRESSE): _tekst(),
        vol.Required(CONF_INNFLYTTET): DateSelector(),
    }
    if not bare_leietaker:
        felt |= {
            vol.Required(CONF_UTLEIER_NAVN): _tekst(),
            vol.Required(CONF_UTLEIER_EPOST): _tekst(type=TextSelectorType.EMAIL),
            vol.Required(CONF_KONTONUMMER): _tekst(),
            vol.Required(
                CONF_FORFALLSDAG, default=d.get(CONF_FORFALLSDAG, DEFAULT_FORFALLSDAG)
            ): _tall(1, 28),
        }
    return vol.Schema(felt)


def schema_kilder(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_ENT_REGNSKAP, default=d.get(CONF_ENT_REGNSKAP, DEFAULT_ENT_REGNSKAP)
            ): _sensor(),
            vol.Required(
                CONF_ENT_UTILITY, default=d.get(CONF_ENT_UTILITY, DEFAULT_ENT_UTILITY)
            ): _sensor(),
            vol.Required(
                CONF_ENT_IMPORT, default=d.get(CONF_ENT_IMPORT, DEFAULT_ENT_IMPORT)
            ): _sensor(),
            vol.Required(
                CONF_MAALER_START_STAND,
                default=d.get(CONF_MAALER_START_STAND, DEFAULT_MAALER_START_STAND),
            ): _tall(0, 100000000, 0.001),
            vol.Required(
                CONF_ENT_EFFEKT, default=d.get(CONF_ENT_EFFEKT, DEFAULT_ENT_EFFEKT)
            ): _sensor(),
            vol.Required(
                CONF_ENT_PROGNOSE, default=d.get(CONF_ENT_PROGNOSE, DEFAULT_ENT_PROGNOSE)
            ): _sensor(),
            vol.Required(
                CONF_VARSEL_TJENESTE, default=d.get(CONF_VARSEL_TJENESTE, DEFAULT_VARSEL_TJENESTE)
            ): _tekst(),
        }
    )


def schema_epost(d: dict[str, Any], *, passord_valgfritt: bool) -> vol.Schema:
    passord_noekkel = (
        vol.Optional(CONF_SMTP_PASSORD, default="")
        if passord_valgfritt
        else vol.Required(CONF_SMTP_PASSORD)
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_SMTP_HOST, default=d.get(CONF_SMTP_HOST, DEFAULT_SMTP_HOST)
            ): _tekst(),
            vol.Required(CONF_SMTP_PORT, default=d.get(CONF_SMTP_PORT, DEFAULT_SMTP_PORT)): _tall(
                1, 65535
            ),
            vol.Required(
                CONF_SMTP_BRUKER, default=d.get(CONF_SMTP_BRUKER, d.get(CONF_UTLEIER_EPOST, ""))
            ): _tekst(),
            passord_noekkel: _tekst(type=TextSelectorType.PASSWORD),
            vol.Required(CONF_CC_UTLEIER, default=d.get(CONF_CC_UTLEIER, True)): BooleanSelector(),
            vol.Required(CONF_SEND_TEST, default=True): BooleanSelector(),
        }
    )


def schema_side(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_PUBLISER_SIDE, default=d.get(CONF_PUBLISER_SIDE, True)
            ): BooleanSelector()
        }
    )


def schema_grenser(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SNITT_MIN, default=d.get(CONF_SNITT_MIN, DEFAULT_SNITT_MIN)): _tall(
                0, 100, 0.01
            ),
            vol.Required(
                CONF_SNITT_MAKS, default=d.get(CONF_SNITT_MAKS, DEFAULT_SNITT_MAKS)
            ): _tall(0, 100, 0.01),
            vol.Required(
                CONF_ENDRING_MAKS, default=d.get(CONF_ENDRING_MAKS, DEFAULT_ENDRING_MAKS)
            ): _tall(1, 1000, 1),
            vol.Required(CONF_KJOREDAG, default=d.get(CONF_KJOREDAG, DEFAULT_KJOREDAG)): _tall(
                1, 28
            ),
            vol.Required(
                CONF_KJORETID, default=d.get(CONF_KJORETID, DEFAULT_KJORETID)
            ): TimeSelector(),
            vol.Required(
                CONF_SISTE_SJEKKDAG, default=d.get(CONF_SISTE_SJEKKDAG, DEFAULT_SISTE_SJEKKDAG)
            ): _tall(1, 28),
        }
    )


# --- validering ---------------------------------------------------------------------------


def valider_leietaker(inn: dict[str, Any]) -> dict[str, str]:
    feil: dict[str, str] = {}
    for felt in (CONF_LEIETAKER_NAVN, CONF_ADRESSE, CONF_UTLEIER_NAVN, CONF_KONTONUMMER):
        if felt in inn and not str(inn[felt]).strip():
            feil[felt] = "paakrevd"
    for felt in (CONF_LEIETAKER_EPOST, CONF_UTLEIER_EPOST):
        if felt in inn and not EPOST_RE.match(inn[felt]):
            feil[felt] = "ugyldig_epost"
    return feil


def valider_kilder(hass: HomeAssistant, inn: dict[str, Any]) -> dict[str, str]:
    domene, _, tjeneste = inn[CONF_VARSEL_TJENESTE].partition(".")
    if not tjeneste or not hass.services.has_service(domene, tjeneste):
        return {CONF_VARSEL_TJENESTE: "tjeneste_finnes_ikke"}
    return {}


def valider_grenser(inn: dict[str, Any]) -> dict[str, str]:
    if float(inn[CONF_SNITT_MIN]) >= float(inn[CONF_SNITT_MAKS]):
        return {CONF_SNITT_MAKS: "snitt_grense"}
    if int(inn[CONF_KJOREDAG]) > int(inn[CONF_SISTE_SJEKKDAG]):
        return {CONF_SISTE_SJEKKDAG: "kjoredag_rekkefolge"}
    return {}


def normaliser(inn: dict[str, Any]) -> dict[str, Any]:
    """NumberSelector gir float; heltallsfelt lagres som int, og test-valget lagres ikke."""
    ut = {k: v for k, v in inn.items() if k != CONF_SEND_TEST}
    for felt in (CONF_FORFALLSDAG, CONF_SMTP_PORT, CONF_KJOREDAG, CONF_SISTE_SJEKKDAG):
        if felt in ut:
            ut[felt] = int(ut[felt])
    for felt in (CONF_SNITT_MIN, CONF_SNITT_MAKS, CONF_ENDRING_MAKS, CONF_MAALER_START_STAND):
        if felt in ut:
            ut[felt] = float(ut[felt])
    return ut


def historikk_tekst() -> str:
    deler = []
    for h in HISTORIKK:
        status = "betalt" if h["status"] == "betalt" else "ikke betalt"
        deler.append(
            f"{h['id']}: {fmt_tall(h['leilighet_kwh'], 1)} kWh × {fmt_tall(h['snitt'], 4)} "
            f"= {fmt_tall(h['belop'], 2)} kr ({status})"
        )
    return "; ".join(deler)
