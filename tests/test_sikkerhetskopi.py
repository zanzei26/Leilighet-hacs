"""Tester for sikkerhetskopier (rene filfunksjoner, ingen Home Assistant)."""

import json
from datetime import datetime, timedelta, timezone

from custom_components.stromregnskap_leietaker.sikkerhetskopi import (
    les_siste_gyldige,
    rydd,
    skriv_kopi,
    velg_a_beholde,
)

OSLO = timezone(timedelta(hours=1))
DATA = {"perioder": [{"id": "2026-10", "belop": 304.25}], "tilstand": {}}


def _t(dag, maaned=12, aar=2026, time=8):
    return datetime(aar, maaned, dag, time, 0, 0, tzinfo=OSLO)


def test_kopi_skrives_med_versjon_tidspunkt_og_data(tmp_path):
    navn = skriv_kopi(str(tmp_path / "kopier"), DATA, _t(3))
    assert navn == "data-20261203-080000.json"
    innhold = json.loads((tmp_path / "kopier" / navn).read_text(encoding="utf-8"))
    assert innhold["versjon"] == 1 and innhold["lagret"].startswith("2026-12-03T08:00:00")
    assert innhold["data"] == DATA


def test_to_kopier_i_samme_sekund_overskriver_ikke_hverandre(tmp_path):
    mappe = str(tmp_path / "k")
    a = skriv_kopi(mappe, DATA, _t(3))
    b = skriv_kopi(mappe, {**DATA, "x": 1}, _t(3))
    assert a != b
    assert len(list((tmp_path / "k").glob("*.json"))) == 2


def test_siste_gyldige_kopi_er_den_nyeste(tmp_path):
    mappe = str(tmp_path)
    skriv_kopi(mappe, {"perioder": [], "tilstand": {}, "id": "gammel"}, _t(1))
    skriv_kopi(mappe, {"perioder": [], "tilstand": {}, "id": "ny"}, _t(2))
    navn, data = les_siste_gyldige(mappe)
    assert navn == "data-20261202-080000.json" and data["id"] == "ny"


def test_ødelagt_nyeste_kopi_hoppes_over(tmp_path):
    mappe = str(tmp_path)
    skriv_kopi(mappe, DATA, _t(1))
    (tmp_path / "data-20261205-080000.json").write_text("{ikke json", encoding="utf-8")
    (tmp_path / "data-20261204-080000.json").write_text(
        '{"versjon":1,"data":"feil"}', encoding="utf-8"
    )
    navn, data = les_siste_gyldige(mappe)
    assert navn == "data-20261201-080000.json" and data == DATA


def test_ingen_mappe_eller_ingen_gyldige_kopier_gir_none(tmp_path):
    assert les_siste_gyldige(str(tmp_path / "finnes_ikke")) is None
    (tmp_path / "data-20261205-080000.json").write_text("søppel", encoding="utf-8")
    assert les_siste_gyldige(str(tmp_path)) is None


def test_fremmede_filer_i_mappen_ignoreres(tmp_path):
    (tmp_path / "notater.txt").write_text("hei", encoding="utf-8")
    skriv_kopi(str(tmp_path), DATA, _t(1))
    assert les_siste_gyldige(str(tmp_path))[0] == "data-20261201-080000.json"


def test_beholder_de_nyeste_og_den_nyeste_fra_hver_eldre_maaned():
    des = [f"data-202612{d:02d}-080000.json" for d in range(1, 26)]  # 25 filer i desember
    nov = ["data-20261128-080000.json", "data-20261130-080000.json"]
    okt = ["data-20261002-080000.json", "data-20261031-080000.json"]
    behold = velg_a_beholde(des + nov + okt, antall=20)
    assert behold >= set(des[-20:])  # de 20 nyeste
    assert "data-20261130-080000.json" in behold and "data-20261031-080000.json" in behold
    assert "data-20261128-080000.json" not in behold and "data-20261002-080000.json" not in behold
    assert "data-20261201-080000.json" not in behold  # desember er allerede dekket av de nyeste
    assert len(behold) == 22


def test_ingen_filer_gir_ingenting_aa_beholde():
    assert velg_a_beholde([]) == set()


def test_rydding_sletter_det_som_ikke_skal_beholdes(tmp_path):
    for d in range(1, 11):
        skriv_kopi(str(tmp_path), DATA, _t(d))
    slettet = rydd(str(tmp_path), antall=4)
    assert slettet == 6
    igjen = sorted(p.name for p in tmp_path.glob("data-*.json"))
    assert igjen == [f"data-202612{d:02d}-080000.json" for d in range(7, 11)]


def test_rydding_roerer_ikke_fremmede_filer(tmp_path):
    (tmp_path / "viktig.txt").write_text("behold", encoding="utf-8")
    for d in range(1, 6):
        skriv_kopi(str(tmp_path), DATA, _t(d))
    rydd(str(tmp_path), antall=2)
    assert (tmp_path / "viktig.txt").exists()
