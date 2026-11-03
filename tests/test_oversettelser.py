"""Sjekker at oversettelser og services.yaml dekker alt integrasjonen viser i UI-et."""

import json
from pathlib import Path

import pytest
import yaml

from custom_components.stromregnskap_leietaker import flow_skjema as cf
from custom_components.stromregnskap_leietaker import services

KAT = Path(__file__).parent.parent / "custom_components" / "stromregnskap_leietaker"
SPRAAK = ("nb", "en")


def _les(spraak):
    return json.loads((KAT / "translations" / f"{spraak}.json").read_text(encoding="utf-8"))


def _flat(d, prefiks=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flat(v, f"{prefiks}{k}.")
        else:
            yield f"{prefiks}{k}"


def _felt(schema):
    return {str(k) for k in schema.schema}


SKJEMAER = {
    "user": _felt(cf.schema_leietaker({})),
    "kilder": _felt(cf.schema_kilder({})),
    "epost": _felt(cf.schema_epost({}, passord_valgfritt=False)),
    "side": _felt(cf.schema_side({})),
    "grenser": _felt(cf.schema_grenser({})),
    "importer": {"importer_historikk"},
    "reconfigure": _felt(cf.schema_leietaker({}, bare_leietaker=True)),
}
FEILKODER = {
    "ugyldig_epost", "paakrevd", "tjeneste_finnes_ikke", "snitt_grense",
    "kjoredag_rekkefolge", "smtp_auth", "smtp_connect", "smtp_send",
}  # fmt: skip
TJENESTER = {
    "generer_oppgjor": {"periode", "tving", "send_epost"},
    "godkjenn_oppgjor": {"periode"},
    "send_epost_pa_nytt": {"periode"},
    "sett_status": {"periode", "status"},
    "publiser_side": set(),
    "slett_periode": {"periode", "bekreft"},
    "ny_leietaker": set(),
}


def test_norsk_og_engelsk_har_noyaktig_samme_noekler():
    assert set(_flat(_les("nb"))) == set(_flat(_les("en")))


def test_strings_json_er_lik_engelsk():
    strings = json.loads((KAT / "strings.json").read_text(encoding="utf-8"))
    assert strings == _les("en")


@pytest.mark.parametrize("spraak", SPRAAK)
@pytest.mark.parametrize("steg", SKJEMAER)
def test_hvert_felt_i_oppsettsflyten_har_tekst(spraak, steg):
    t = _les(spraak)["config"]["step"][steg]
    assert t["title"] and t["description"]
    manglende = SKJEMAER[steg] - set(t["data"])
    assert not manglende, f"{steg}: mangler tekst for {manglende}"


@pytest.mark.parametrize("spraak", SPRAAK)
@pytest.mark.parametrize(
    "steg", [s for s in SKJEMAER if s not in ("user", "importer", "reconfigure")]
)
def test_hvert_felt_i_valgflyten_har_tekst(spraak, steg):
    t = _les(spraak)["options"]["step"][steg]
    assert t["title"]
    assert not SKJEMAER[steg] - set(t["data"])


@pytest.mark.parametrize("spraak", SPRAAK)
def test_valgflyten_har_menyvalg_og_leietakerside(spraak):
    o = _les(spraak)["options"]["step"]
    assert set(o["init"]["menu_options"]) == {"leietaker", "kilder", "epost", "side", "grenser"}
    assert set(SKJEMAER["user"]) <= set(o["leietaker"]["data"])


@pytest.mark.parametrize("spraak", SPRAAK)
def test_alle_feilkoder_og_avbrudd_har_tekst(spraak):
    t = _les(spraak)
    assert FEILKODER <= set(t["config"]["error"])
    assert FEILKODER <= set(t["options"]["error"])
    assert {"single_instance_allowed", "reconfigure_successful"} <= set(t["config"]["abort"])


@pytest.mark.parametrize("spraak", SPRAAK)
def test_plassholdere_finnes_i_teksten(spraak):
    c = _les(spraak)["config"]["step"]
    assert "{lenke}" in c["side"]["description"]
    assert "{historikk}" in c["importer"]["description"]
    assert "{lenke}" in _les(spraak)["options"]["step"]["side"]["description"]


@pytest.mark.parametrize("spraak", SPRAAK)
def test_issues_har_tittel_beskrivelse_og_fiksflyt(spraak):
    i = _les(spraak)["issues"]
    for art in ("venter_godkjenning", "mangler_data", "epost_feilet"):
        assert i[art]["title"]
    assert "{periode}" in i["venter_godkjenning"]["fix_flow"]["step"]["confirm"]["description"]
    assert "{maned}" in i["venter_godkjenning"]["title"]
    assert "{entitet}" in i["mangler_data"]["description"]
    assert "{detaljer}" in i["venter_godkjenning"]["description"]
    for art in ("venter_godkjenning", "epost_feilet"):
        assert "{feil}" in i[art]["fix_flow"]["abort"]["handling_feilet"]


@pytest.mark.parametrize("spraak", SPRAAK)
def test_alle_tjenester_og_felt_har_navn_og_beskrivelse(spraak):
    t = _les(spraak)["services"]
    assert set(t) == set(TJENESTER)
    for navn, felt in TJENESTER.items():
        assert t[navn]["name"] and t[navn]["description"]
        assert felt == set(t[navn].get("fields", {}))
        for f in t[navn].get("fields", {}).values():
            assert f["name"] and f["description"]


def test_services_yaml_samsvarer_med_registrerte_tjenester():
    y = yaml.safe_load((KAT / "services.yaml").read_text(encoding="utf-8"))
    assert set(y) == set(TJENESTER)
    for navn, felt in TJENESTER.items():
        assert set((y[navn] or {}).get("fields", {})) == felt


def test_hacs_json_og_manifest_henger_sammen():
    manifest = json.loads((KAT / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((KAT.parent.parent / "hacs.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "stromregnskap_leietaker"
    assert manifest["iot_class"] == "calculated" and manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert hacs["name"] and "homeassistant" in hacs


def test_skjemaene_i_services_py_stemmer_med_testens_forventning():
    # beskytter mot at noen legger til et tjenestefelt uten tekst
    assert {str(k) for k in services.SKJEMA_GENERER.schema} == TJENESTER["generer_oppgjor"]
    assert {str(k) for k in services.SKJEMA_STATUS.schema} == TJENESTER["sett_status"]
    assert {str(k) for k in services.SKJEMA_SLETT.schema} == TJENESTER["slett_periode"]
