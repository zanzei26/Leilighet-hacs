"""Utsending av oppgjøret til leietaker, med nytt forsøk hver time i inntil 48 timer."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .calc import STATUS_VENTER
from .const import (
    CONF_CC_UTLEIER,
    CONF_KOPI_TIL_UTLEIER,
    CONF_PUBLISER_SIDE,
    CONF_SMTP_BRUKER,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSORD,
    CONF_SMTP_PORT,
    EPOST_MAKS_TIMER,
)
from .filnavn import REGNSKAPSNAVN, fakturanavn
from .generering import sammendrag
from .mail import SmtpFeil, bygg_epost, bygg_kopipost, bygg_lenkepost, send_epost
from .varsler import ISSUE_EPOST

_LOGGER = logging.getLogger(__name__)


class EpostMixin:
    """Metoder for StromregnskapCoordinator."""

    async def _send_melding(self, melding) -> None:
        """Sender en ferdig bygget melding via SMTP i executor. Kaster SmtpFeil."""
        c = self.cfg
        await self.hass.async_add_executor_job(
            partial(
                send_epost,
                host=c[CONF_SMTP_HOST],
                port=int(c[CONF_SMTP_PORT]),
                brukernavn=c[CONF_SMTP_BRUKER],
                passord=c[CONF_SMTP_PASSORD],
                melding=melding,
            )
        )

    async def async_send_lenke(self) -> None:
        """Sender en kort e-post til leietaker med lenken til leietakersiden."""
        if not self.cfg.get(CONF_PUBLISER_SIDE):
            raise ServiceValidationError(
                "Leietakersiden er slått av. Slå den på under Konfigurer → Leietakerside først."
            )
        url = self.side_url
        if url is None:
            raise ServiceValidationError(
                "Home Assistant kjenner ingen ekstern adresse å lage lenken av. "
                "Slå på Nabu Casa eller sett ekstern URL, og prøv igjen."
            )
        melding = bygg_lenkepost(
            leietaker=self.leietaker,
            utleier=self.utleier,
            side_url=url,
            cc_utleier=bool(self.cfg.get(CONF_CC_UTLEIER, True)),
        )
        try:
            await self._send_melding(melding)
        except SmtpFeil as err:
            _LOGGER.warning("Lenken kunne ikke sendes (%s): %s", err.kind, err)
            raise HomeAssistantError(f"Lenken kunne ikke sendes ({err.kind}): {err}") from err
        await self.varsler.varsle(
            "Lenke sendt", f"Lenken til leietakersiden er sendt til {self.leietaker['epost']}."
        )

    async def async_send_kopi(self, periode_id: str | None = None) -> None:
        """Sender kopi til utleier: fakturagrunnlag, hele regnskapet og JSON-sikkerhetskopi."""
        naa = dt_util.now()
        if periode_id is None:
            synlige = self.synlige_perioder()
            if not synlige:
                raise ServiceValidationError("Det finnes ingen oppgjør å sende kopi av ennå.")
            periode_id = max(synlige, key=lambda p: p["id"])["id"]
        p = self._hent_periode(periode_id)
        if p["status"] == STATUS_VENTER:
            raise ServiceValidationError(
                f"Perioden {periode_id} venter på godkjenning og kan ikke sendes ennå."
            )
        faktura = await self.async_faktura_pdf(periode_id, naa)
        regnskap = await self.async_regnskap_pdf(naa)
        melding = bygg_kopipost(
            periode=p,
            leietaker=self.leietaker,
            utleier=self.utleier,
            vedlegg=[
                (fakturanavn(periode_id), "application/pdf", faktura),
                (REGNSKAPSNAVN, "application/pdf", regnskap),
                (
                    f"stromregnskap-sikkerhetskopi-{naa:%Y%m%d}.json",
                    "application/json",
                    self.sikkerhetsjson(naa),
                ),
            ],
        )
        try:
            await self._send_melding(melding)
        except SmtpFeil as err:
            _LOGGER.warning("Kopien for %s kunne ikke sendes (%s): %s", periode_id, err.kind, err)
            raise HomeAssistantError(f"Kopien kunne ikke sendes ({err.kind}): {err}") from err

    async def _send_kopi_stille(self, p: dict[str, Any]) -> None:
        """Automatisk kopi etter utsending til leietaker. Feil her stopper aldri oppgjøret."""
        if not self.cfg.get(CONF_KOPI_TIL_UTLEIER, True):
            return
        try:
            await self.async_send_kopi(p["id"])
        except HomeAssistantError as err:
            await self.varsler.varsle_en_gang(
                f"kopi_feilet:{p['id']}",
                "Kopi til utleier feilet",
                f"Kopien av oppgjøret for {p['id']} kunne ikke sendes til deg: {err}",
            )

    async def _send_epost(self, p: dict[str, Any], naa: datetime) -> SmtpFeil | None:
        """Sender oppgjøret. Returnerer None ved suksess, ellers feilen."""
        c = self.cfg
        self._forsokt_na.add(p["id"])
        melding = bygg_epost(
            periode=p,
            leietaker=self.leietaker,
            utleier=self.utleier,
            side_url=self.side_url,
            cc_utleier=bool(c.get(CONF_CC_UTLEIER, True)),
        )
        try:
            await self._send_melding(melding)
        except SmtpFeil as err:
            _LOGGER.warning("E-post for oppgjør %s feilet (%s): %s", p["id"], err.kind, err)
            if not p.get("epost_ventende_siden"):
                p["epost_ventende_siden"] = naa.isoformat()
            await self.lager.async_lagre()
            await self.varsler.varsle_en_gang(
                f"{ISSUE_EPOST}:{p['id']}",
                "Strømoppgjør: e-post feilet",
                f"E-post for oppgjør {p['id']} feilet ({err.kind}). "
                f"Prøver igjen hver time i inntil {EPOST_MAKS_TIMER} timer.",
            )
            return err

        p["epost_sendt"] = naa.isoformat()
        p["epost_ventende_siden"] = None
        await self.lager.async_lagre()
        self.varsler.fjern_issue(ISSUE_EPOST, p["id"])
        await self.varsler.varsle("Strømoppgjør sendt", f"Oppgjør {p['id']} sendt: {sammendrag(p)}")
        await self._send_kopi_stille(p)
        return None

    async def _send_ventende(self, naa: datetime) -> None:
        """Nytt forsøk for e-post som ikke gikk gjennom. Etter 48 timer: Repairs-issue."""
        for p in list(self.lager.perioder):
            siden = p.get("epost_ventende_siden")
            if not siden or p["status"] == STATUS_VENTER or p.get("epost_sendt"):
                continue
            if p["id"] in self._forsokt_na:
                continue  # allerede forsøkt i denne kjøringen
            if naa - datetime.fromisoformat(siden) >= timedelta(hours=EPOST_MAKS_TIMER):
                self.varsler.opprett_issue(
                    ISSUE_EPOST, p["id"], fixable=True, severity=ir.IssueSeverity.ERROR
                )
                continue
            await self._send_epost(p, naa)

    async def async_send_epost_pa_nytt(self, periode_id: str) -> None:
        p = self._hent_periode(periode_id)
        if p["status"] == STATUS_VENTER:
            raise ServiceValidationError(
                f"Perioden {periode_id} venter på godkjenning. Bruk godkjenn_oppgjor."
            )
        naa = dt_util.now()
        p["epost_ventende_siden"] = naa.isoformat()
        feil = await self._send_epost(p, naa)
        self.async_set_updated_data(await self._publiser(naa))
        if feil:
            raise HomeAssistantError(f"E-post for {periode_id} feilet ({feil.kind}): {feil}")
