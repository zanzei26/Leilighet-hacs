"""Tester for rendering av leietakersiden."""

from copy import deepcopy

from custom_components.stromregnskap_leietaker.page import fmt_dato, fmt_tall, render_side

from .data import LEIETAKER, OKT, perioder, side_ctx


def test_tall_bruker_komma_og_mellomrom_som_tusenskille():
    assert fmt_tall(1234.5, 2) == "1 234,50"
    assert fmt_tall(1019, 0) == "1 019"
    assert fmt_tall(1.3002, 4) == "1,3002"
    assert fmt_tall(-3.5, 1) == "-3,5"


def test_dato_formateres_dd_mm_aaaa():
    assert fmt_dato("2026-11-15") == "15.11.2026"


def test_siden_har_noindex_og_lys_morkt_og_ingen_eksterne_ressurser():
    html = render_side(side_ctx())
    assert 'name="robots" content="noindex,nofollow"' in html
    assert "prefers-color-scheme: dark" in html
    assert "<script" not in html
    assert 'src="http' not in html and 'href="http' not in html
    assert 'lang="nb"' in html


def test_siden_viser_adresse_leietaker_og_utleier():
    html = render_side(side_ctx())
    assert "Testveien 1, 1. etasje" in html
    assert "Kari Nordmann" in html
    assert "Ola Utleier" in html
    assert "30.08.2026" in html


def test_utestaaende_og_betalingsinfo_vises():
    html = render_side(side_ctx())
    assert "304,25" in html
    assert "Ikke betalt" in html
    assert "1234.56.78903" in html
    assert "Strøm – oktober 2026" in html
    assert "15." in html


def test_alt_betalt_gir_betalt_merke_og_null_utestaaende():
    ps = perioder()
    ps[1]["status"] = "betalt"
    html = render_side(side_ctx(perioder=ps))
    assert "Betalt" in html
    assert "0,00" in html


def test_historikk_har_nyeste_periode_oeverst_og_totalt_utestaaende_nederst():
    html = render_side(side_ctx())
    tabell = html[html.index("<table") : html.index("</table>")]
    assert tabell.index("oktober 2026") < tabell.index("september 2026")
    assert "228,0" in tabell and "234,0" in tabell
    assert "1,3280" in tabell and "1,3002" in tabell
    assert "302,79" in tabell and "304,25" in tabell
    assert tabell.rindex("304,25") > tabell.index("september 2026")  # totalen står sist


def test_forste_periode_viser_innflyttingsdato_siden_den_ikke_er_hel_maned():
    html = render_side(side_ctx())
    tabell = html[html.index("<table") : html.index("</table>")]
    assert "september 2026 (30.08.–30.09.)" in tabell
    assert "oktober 2026 (" not in tabell  # hel måned: ingen datoer


def test_periode_som_venter_godkjenning_vises_ikke_og_telles_ikke():
    ps = perioder()
    ny = deepcopy(OKT)
    ny.update(
        {
            "id": "2026-11",
            "start": "2026-11-01",
            "slutt": "2026-12-01",
            "status": "venter_godkjenning",
            "belop": 999.99,
            "leilighet_kwh": 777.7,
        }
    )
    ps.append(ny)
    html = render_side(side_ctx(perioder=ps))
    assert "999,99" not in html and "november 2026" not in html


def test_hittil_viser_tre_tall_og_forklaring():
    html = render_side(side_ctx())
    assert "21,9" in html or "21,85" in html
    assert "3,1434" in html
    assert "68,40" in html
    assert "faste ledd" in html


def test_estimat_vises_med_ca():
    html = render_side(side_ctx())
    assert "ca. 285 kWh" in html
    assert "ca. 371 kr" in html


def test_oppdatert_tidspunkt_vises():
    assert "03.11.2026 17:20" in render_side(side_ctx())


def test_uten_hittil_og_estimat_vises_tankestrek_uten_feil():
    html = render_side(side_ctx(hittil=None, estimat=None))
    assert "–" in html
    assert "ca." not in html


def test_uten_perioder_rendres_siden_uten_feil():
    html = render_side(side_ctx(perioder=[]))
    assert "Ingen oppgjør ennå" in html
    assert "0,00" in html


def test_utregningsseksjon_viser_husets_tall_for_siste_maned():
    html = render_side(side_ctx())
    seksjon = html[html.index("<details") : html.index("</details>")]
    assert "Slik er beløpet regnet ut" in seksjon
    for tall in ("2 402,13", "4 635,08", "1 786,72", "3 298,51", "3 123,30", "1,3002"):
        assert tall in seksjon
    assert "oktober 2026" in seksjon


def test_html_i_navn_blir_escapet():
    ctx = side_ctx(leietaker={**LEIETAKER, "navn": "<script>alert(1)</script>"})
    html = render_side(ctx)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_ikke_betalt_og_unntak_vises_begge_som_ikke_betalt():
    ps = perioder()
    ps[0]["status"] = "unntak_ikke_betalt"
    html = render_side(side_ctx(perioder=ps))
    assert "607,04" in html  # 302,79 + 304,25 regnes begge som utestående
