"""Tester for nedlasting av PDF bak den hemmelige lenken (ingen innlogging)."""

import io
from copy import deepcopy

from pypdf import PdfReader

from .data import OKT

SLUG = "testslug123"
REGNSKAP = f"/stromregnskap/{SLUG}/regnskap-strom-leilighet.pdf"
FAKTURA = f"/stromregnskap/{SLUG}/fakturagrunnlag-strom-leilighet-2026-10.pdf"


def _tekst(data: bytes) -> str:
    return "\n".join(s.extract_text() for s in PdfReader(io.BytesIO(data), strict=True).pages)


async def test_regnskapet_lastes_ned_uten_innlogging_som_vedlegg_uten_cache(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    svar = await klient.get(REGNSKAP)
    assert svar.status == 200
    assert svar.content_type == "application/pdf"
    assert (
        svar.headers["Content-Disposition"] == 'attachment; filename="regnskap-strom-leilighet.pdf"'
    )
    assert svar.headers["Cache-Control"] == "no-store"
    assert "noindex" in svar.headers["X-Robots-Tag"]
    tekst = _tekst(await svar.read())
    assert "Regnskap" in tekst and "304,25" in tekst and "302,79" in tekst


async def test_fakturagrunnlag_for_en_periode_lastes_ned(hass, integrasjon, hass_client_no_auth):
    klient = await hass_client_no_auth()
    svar = await klient.get(FAKTURA)
    assert svar.status == 200 and svar.content_type == "application/pdf"
    assert (
        'filename="fakturagrunnlag-strom-leilighet-2026-10.pdf"'
        in svar.headers["Content-Disposition"]
    )
    tekst = _tekst(await svar.read())
    assert "Fakturagrunnlag" in tekst and "oktober 2026" in tekst and "304,25" in tekst


async def test_innholdet_er_alltid_ferskt(hass, integrasjon, hass_client_no_auth):
    klient = await hass_client_no_auth()
    assert "Ikke betalt" in _tekst(await (await klient.get(FAKTURA)).read())
    await hass.services.async_call("stromregnskap_leietaker", "merk_betalt", {}, blocking=True)
    tekst = _tekst(await (await klient.get(FAKTURA)).read())
    assert "Ikke betalt" not in tekst and "Betalt" in tekst


async def test_feil_slug_ukjent_periode_og_ugyldige_navn_gir_404(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    for sti in (
        "/stromregnskap/feil-slug/regnskap-strom-leilighet.pdf",
        f"/stromregnskap/{SLUG}/fakturagrunnlag-strom-leilighet-2099-01.pdf",
        f"/stromregnskap/{SLUG}/fakturagrunnlag-strom-leilighet-2026-13.pdf",
        f"/stromregnskap/{SLUG}/noe-annet.pdf",
        f"/stromregnskap/{SLUG}/regnskap-strom-leilighet.txt",
    ):
        assert (await klient.get(sti)).status == 404, sti
    # stiforsøk avvises allerede av Home Assistants sikkerhetsfilter (400), aldri 200
    assert (await klient.get(f"/stromregnskap/{SLUG}/..%2Fsecret.pdf")).status in (400, 404)


async def test_oppgjor_som_venter_paa_godkjenning_er_ikke_tilgjengelig_for_leietaker(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    lager = integrasjon.entry.runtime_data.lager
    ny = deepcopy(OKT)
    ny.update({"id": "2026-11", "status": "venter_godkjenning", "belop": 999.99})
    lager.legg_til(ny)
    svar = await klient.get(f"/stromregnskap/{SLUG}/fakturagrunnlag-strom-leilighet-2026-11.pdf")
    assert svar.status == 404
    assert "999,99" not in _tekst(await (await klient.get(REGNSKAP)).read())


async def test_nedlasting_stopper_naar_integrasjonen_lastes_ut(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    assert (await klient.get(REGNSKAP)).status == 200
    assert await hass.config_entries.async_unload(integrasjon.entry.entry_id)
    await hass.async_block_till_done()
    assert (await klient.get(REGNSKAP)).status == 404


async def test_ingen_nedlasting_naar_siden_ikke_publiseres(hass, integrasjon, hass_client_no_auth):
    klient = await hass_client_no_auth()
    hass.config_entries.async_update_entry(
        integrasjon.entry, data={**integrasjon.entry.data, "publiser_side": False}
    )
    await hass.async_block_till_done()
    assert (await klient.get(REGNSKAP)).status == 404
