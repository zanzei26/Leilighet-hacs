"""Manuelle handlinger: godkjenn, sett status, slett periode, leietakerskifte, publiser."""

from __future__ import annotations

import secrets
from copy import deepcopy

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .calc import (
    GYLDIGE_MANUELLE_STATUSER,
    STATUS_BETALT,
    STATUS_IKKE_BETALT,
    STATUS_VENTER,
    UTESTAAENDE_STATUSER,
)
from .const import CONF_SLUG, DOMAIN, SLUG_LENGDE_BYTES
from .filer import fjern_mappe, skriv_arkiv
from .url import bygg_side_url
from .varsler import ISSUE_VENTER


class HandlingerMixin:
    """Metoder for StromregnskapCoordinator."""

    async def async_godkjenn_oppgjor(self, periode_id: str) -> None:
        p = self._hent_periode(periode_id)
        if p["status"] != STATUS_VENTER:
            raise ServiceValidationError(f"Perioden {periode_id} venter ikke på godkjenning.")
        naa = dt_util.now()
        p["status"] = STATUS_IKKE_BETALT
        p["notat"] = f"{p.get('notat', '')} | godkjent manuelt {naa.date().isoformat()}".strip(" |")
        p["epost_ventende_siden"] = naa.isoformat()
        await self.lager.async_lagre()
        self.varsler.fjern_issue(ISSUE_VENTER, periode_id)
        await self._skriv_side(naa)
        await self._send_epost(p, naa)
        self.async_set_updated_data(await self._publiser(naa))

    async def async_sett_status(self, periode_id: str, status: str) -> None:
        p = self._hent_periode(periode_id)
        if status not in GYLDIGE_MANUELLE_STATUSER:
            raise ServiceValidationError(
                f"Ugyldig status «{status}». Velg blant: {', '.join(GYLDIGE_MANUELLE_STATUSER)}."
            )
        if p["status"] == STATUS_VENTER:
            raise ServiceValidationError(
                f"Perioden {periode_id} venter på godkjenning. Bruk godkjenn_oppgjor."
            )
        p["status"] = status
        await self.lager.async_lagre()
        self.async_set_updated_data(await self._publiser(dt_util.now()))

    async def async_merk_betalt(self, periode_id: str | None = None) -> list[str]:
        """Merker utestående perioder som betalt. Uten periode: alle utestående.

        Oppgjør som venter på godkjenning er ikke utestående og røres ikke.
        """
        if periode_id is not None:
            p = self._hent_periode(periode_id)
            if p["status"] not in UTESTAAENDE_STATUSER:
                raise ServiceValidationError(f"Perioden {periode_id} er ikke utestående.")
            valgt = [p]
        else:
            valgt = [p for p in self.lager.perioder if p["status"] in UTESTAAENDE_STATUSER]
            if not valgt:
                raise ServiceValidationError("Det er ingenting utestående å merke som betalt.")
        for p in valgt:
            p["status"] = STATUS_BETALT
        await self.lager.async_lagre()
        self.async_set_updated_data(await self._publiser(dt_util.now()))
        return [p["id"] for p in valgt]

    async def async_slett_periode(self, periode_id: str, *, bekreft: bool) -> None:
        self._hent_periode(periode_id)
        if not bekreft:
            raise ServiceValidationError(
                "Sletting må bekreftes med bekreft: true. Et sendt oppgjør kan ikke angres."
            )
        self.lager.fjern(periode_id)
        self.lager.tilstand["varslet"] = [
            k for k in self.lager.tilstand["varslet"] if not k.endswith(f":{periode_id}")
        ]
        await self.lager.async_lagre()
        self.varsler.fjern_alle_issues(periode_id)
        self.async_set_updated_data(await self._publiser(dt_util.now()))

    async def async_publiser_side(self) -> None:
        self.async_set_updated_data(await self._publiser(dt_util.now()))

    async def async_ny_leietaker(self) -> dict[str, str | None]:
        """Leietakerskifte: arkiver, tøm historikk, ny lenke og åpne rekonfigurering."""
        naa = dt_util.now()
        gammel_slug = self.cfg[CONF_SLUG]
        arkiv = {
            "arkivert": naa.isoformat(),
            "leietaker": self.leietaker,
            "utleier": self.utleier,
            "perioder": deepcopy(self.lager.perioder),
            "tilstand": deepcopy(self.lager.tilstand),
        }
        basisnavn = f"{slugify(self.leietaker['navn'])}_{naa.date().isoformat()}"
        arkiv_sti = await self.hass.async_add_executor_job(
            skriv_arkiv,
            self.hass.config.path("stromregnskap_leietaker", "arkiv"),
            basisnavn,
            arkiv,
        )

        for p in self.lager.perioder:
            self.varsler.fjern_alle_issues(p["id"])
        self.lager.tom_historikk()
        await self.lager.async_lagre()

        # den gamle lenken skal dø med en gang, også før integrasjonen er lastet på nytt
        self.hass.data[DOMAIN]["aktive_slugs"].pop(gammel_slug, None)
        self.hass.data[DOMAIN]["koordinatorer"].pop(gammel_slug, None)
        await self.hass.async_add_executor_job(
            fjern_mappe, self.hass.config.path("www", gammel_slug)
        )
        ny_slug = secrets.token_urlsafe(SLUG_LENGDE_BYTES)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_SLUG: ny_slug}
        )  # starter en omlasting via oppdateringslytteren
        await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": self.entry.entry_id},
        )
        return {"arkiv": arkiv_sti, "ny_lenke": bygg_side_url(self.hass, ny_slug)}
