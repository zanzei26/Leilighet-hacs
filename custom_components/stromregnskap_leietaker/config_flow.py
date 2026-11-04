"""Oppsett via UI: config flow, valgflyt (alt kan endres) og rekonfigurering."""

from __future__ import annotations

import secrets
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
)

from .const import (
    CONF_IMPORTER_HISTORIKK,
    CONF_SEND_TEST,
    CONF_SLUG,
    CONF_SMTP_BRUKER,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSORD,
    CONF_SMTP_PORT,
    CONF_UTLEIER_EPOST,
    CONF_UTLEIER_NAVN,
    CONF_UTLEIER_TELEFON,
    DOMAIN,
    SLUG_LENGDE_BYTES,
)
from .flow_skjema import (
    INGEN_LENKE,
    historikk_tekst,
    normaliser,
    schema_epost,
    schema_grenser,
    schema_kilder,
    schema_leietaker,
    schema_side,
    valider_grenser,
    valider_kilder,
    valider_leietaker,
)
from .mail import SmtpFeil, bygg_testepost, sjekk_smtp
from .url import bygg_side_url


async def valider_epost(
    hass: HomeAssistant, inn: dict[str, Any], passord: str, utleier: dict[str, Any]
) -> dict[str, str]:
    """Logger inn mot SMTP (og sender eventuelt en test-e-post til utleier)."""
    test = bygg_testepost(utleier) if inn.get(CONF_SEND_TEST) else None
    try:
        await hass.async_add_executor_job(
            partial(
                sjekk_smtp,
                host=inn[CONF_SMTP_HOST],
                port=int(inn[CONF_SMTP_PORT]),
                brukernavn=inn[CONF_SMTP_BRUKER],
                passord=passord,
                testmelding=test,
            )
        )
    except SmtpFeil as err:
        return {"base": f"smtp_{err.kind}"}
    return {}


# --- oppsettsflyt --------------------------------------------------------------------------


class StromregnskapConfigFlow(ConfigFlow, domain=DOMAIN):
    """Fem trinn pluss valg om import av eksisterende historikk."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._slug = secrets.token_urlsafe(SLUG_LENGDE_BYTES)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> StromregnskapOptionsFlow:
        return StromregnskapOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_leietaker(user_input)
            if not feil:
                self._data |= normaliser(user_input)
                return await self.async_step_kilder()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema_leietaker({}), user_input or self._data
            ),
            errors=feil,
        )

    async def async_step_kilder(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_kilder(self.hass, user_input)
            if not feil:
                self._data |= normaliser(user_input)
                return await self.async_step_epost()
        return self.async_show_form(
            step_id="kilder", data_schema=schema_kilder(user_input or self._data), errors=feil
        )

    async def async_step_epost(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            utleier = {
                "navn": self._data[CONF_UTLEIER_NAVN],
                "epost": self._data[CONF_UTLEIER_EPOST],
            }
            feil = await valider_epost(
                self.hass, user_input, user_input[CONF_SMTP_PASSORD], utleier
            )
            if not feil:
                self._data |= normaliser(user_input)
                return await self.async_step_side()
        return self.async_show_form(
            step_id="epost",
            data_schema=schema_epost(user_input or self._data, passord_valgfritt=False),
            errors=feil,
        )

    async def async_step_side(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data |= normaliser(user_input) | {CONF_SLUG: self._slug}
            return await self.async_step_grenser()
        return self.async_show_form(
            step_id="side",
            data_schema=schema_side(self._data),
            description_placeholders={"lenke": bygg_side_url(self.hass, self._slug) or INGEN_LENKE},
        )

    async def async_step_grenser(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_grenser(user_input)
            if not feil:
                self._data |= normaliser(user_input)
                return await self.async_step_importer()
        return self.async_show_form(
            step_id="grenser", data_schema=schema_grenser(user_input or self._data), errors=feil
        )

    async def async_step_importer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data |= user_input
            return self.async_create_entry(title="Strømregnskap leietaker", data=self._data)
        return self.async_show_form(
            step_id="importer",
            data_schema=vol.Schema(
                {vol.Required(CONF_IMPORTER_HISTORIKK, default=True): BooleanSelector()}
            ),
            description_placeholders={"historikk": historikk_tekst()},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Nye leietakerdata (brukes av ny_leietaker ved leietakerskifte)."""
        entry = self._get_reconfigure_entry()
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_leietaker(user_input)
            if not feil:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema_leietaker({}, bare_leietaker=True), user_input or dict(entry.data)
            ),
            errors=feil,
        )


# --- valgflyt: alt kan endres etterpå -----------------------------------------------------------


class StromregnskapOptionsFlow(OptionsFlow):
    """Meny med én side per tema. Endringer skrives til entry.data og laster på nytt."""

    def _lagre(self, nye: dict[str, Any]):
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, **nye}
        )
        return self.async_create_entry(data=self.config_entry.options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["leietaker", "kilder", "epost", "side", "grenser"]
        )

    async def async_step_leietaker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_leietaker(user_input)
            if not feil:
                return self._lagre(normaliser(user_input))
        return self.async_show_form(
            step_id="leietaker",
            data_schema=self.add_suggested_values_to_schema(
                schema_leietaker({}), user_input or dict(self.config_entry.data)
            ),
            errors=feil,
        )

    async def async_step_kilder(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_kilder(self.hass, user_input)
            if not feil:
                return self._lagre(normaliser(user_input))
        return self.async_show_form(
            step_id="kilder",
            data_schema=schema_kilder(user_input or dict(self.config_entry.data)),
            errors=feil,
        )

    async def async_step_epost(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        gjeldende = dict(self.config_entry.data)
        feil: dict[str, str] = {}
        if user_input is not None:
            passord = user_input.get(CONF_SMTP_PASSORD) or gjeldende[CONF_SMTP_PASSORD]
            utleier = {"navn": gjeldende[CONF_UTLEIER_NAVN], "epost": gjeldende[CONF_UTLEIER_EPOST]}
            feil = await valider_epost(self.hass, user_input, passord, utleier)
            if not feil:
                return self._lagre(normaliser({**user_input, CONF_SMTP_PASSORD: passord}))
        return self.async_show_form(
            step_id="epost",
            data_schema=schema_epost(user_input or gjeldende, passord_valgfritt=True),
            errors=feil,
        )

    async def async_step_side(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # et tomt valgfritt felt kommer ikke med i skjemaet: det betyr «fjern», ikke «behold»
            nye = {CONF_UTLEIER_TELEFON: ""} | normaliser(user_input)
            return self._lagre(nye)
        slug = self.config_entry.data[CONF_SLUG]
        return self.async_show_form(
            step_id="side",
            data_schema=schema_side(dict(self.config_entry.data)),
            description_placeholders={"lenke": bygg_side_url(self.hass, slug) or INGEN_LENKE},
        )

    async def async_step_grenser(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        feil: dict[str, str] = {}
        if user_input is not None:
            feil = valider_grenser(user_input)
            if not feil:
                return self._lagre(normaliser(user_input))
        return self.async_show_form(
            step_id="grenser",
            data_schema=schema_grenser(user_input or dict(self.config_entry.data)),
            errors=feil,
        )
