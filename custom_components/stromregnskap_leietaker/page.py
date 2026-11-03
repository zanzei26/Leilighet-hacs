"""Rendering av leietakersiden som én selvstendig HTML-fil.

Ren funksjon: tar en dict og returnerer en streng. Ingen HA-avhengigheter,
ingen eksterne ressurser og ingen JavaScript.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from .calc import STATUS_BETALT, STATUS_VENTER, avrund, utestaaende
from .filnavn import REGNSKAPSNAVN, fakturanavn

MAANEDER = (
    "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
)  # fmt: skip

NBSP = " "


def fmt_tall(verdi: float | int, desimaler: int = 2) -> str:
    """Norsk tallformat: mellomrom som tusenskille, komma som desimal."""
    v = avrund(verdi, desimaler)
    tekst = f"{abs(v):,.{desimaler}f}".replace(",", NBSP).replace(".", ",")
    return f"-{tekst}" if v < 0 else tekst


def fmt_kwh(verdi: float | int) -> str:
    """kWh med én desimal (halvt opp). Tilstrekkelig, og lett å kontrollere for hånd."""
    return fmt_tall(verdi, 1)


def fmt_dato(iso: str) -> str:
    """ISO-dato (YYYY-MM-DD) til dd.mm.åååå."""
    return date.fromisoformat(iso).strftime("%d.%m.%Y")


def maaned_tekst(periode_id: str) -> str:
    """«2026-10» → «oktober 2026»."""
    aar, mnd = periode_id.split("-")
    return f"{MAANEDER[int(mnd) - 1]} {aar}"


def periode_tekst(p: dict[str, Any]) -> str:
    """Månedsnavn, og datointervall hvis perioden ikke starter den 1."""
    tekst = maaned_tekst(p["id"])
    start = date.fromisoformat(p["start"])
    if start.day != 1:
        siste = date.fromisoformat(p["slutt"]) - timedelta(days=1)
        tekst += f" ({start.strftime('%d.%m.')}–{siste.strftime('%d.%m.')})"
    return tekst


def _e(verdi: Any) -> str:
    return escape(str(verdi), quote=True)


def _status_tekst(status: str) -> str:
    return "Betalt" if status == STATUS_BETALT else "Ikke betalt"


def _tidspunkt(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")


CSS = """
:root { color-scheme: light dark; --bg:#f6f7f9; --kort:#fff; --tekst:#1b1f24; --dempet:#5c6670;
  --linje:#e1e5ea; --ok:#1a7f45; --ok-bg:#e3f4ea; --advarsel:#a4560b; --advarsel-bg:#fdf0e1; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14171a; --kort:#1e2227; --tekst:#e8ebee; --dempet:#9aa4ae; --linje:#2e343b;
    --ok:#5fd18b; --ok-bg:#16301f; --advarsel:#f0a45a; --advarsel-bg:#3a2a14; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--tekst);
  font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width:720px; margin:0 auto; padding:16px; }
h1 { font-size:1.4rem; margin:8px 0 2px; }
h2 { font-size:1.05rem; margin:0 0 8px; }
.sub { color:var(--dempet); margin:0 0 16px; }
.kort { background:var(--kort); border:1px solid var(--linje); border-radius:12px;
  padding:16px; margin:0 0 16px; }
.stor { font-size:2rem; font-weight:700; line-height:1.2; }
.merke { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.85rem;
  font-weight:600; vertical-align:middle; margin-left:8px; }
.merke.ok { background:var(--ok-bg); color:var(--ok); }
.merke.ubetalt { background:var(--advarsel-bg); color:var(--advarsel); }
.tre { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; text-align:center; }
.tre .tall { font-size:1.35rem; font-weight:700; }
.tre .tekst { color:var(--dempet); font-size:.85rem; }
.liten { color:var(--dempet); font-size:.875rem; }
dl { display:grid; grid-template-columns:auto 1fr; gap:4px 16px; margin:8px 0; }
dt { color:var(--dempet); }
dd { margin:0; font-weight:600; }
table { width:100%; border-collapse:collapse; font-size:.9rem; }
th, td { padding:6px 4px; text-align:right; border-bottom:1px solid var(--linje); }
th:first-child, td:first-child { text-align:left; }
tfoot td { font-weight:700; border-bottom:0; }
.rull { overflow-x:auto; }
summary { cursor:pointer; font-weight:600; }
.knapp { display:inline-block; margin-top:4px; padding:4px 10px; border:1px solid var(--linje); border-radius:8px;
  text-decoration:none; color:var(--tekst); font-weight:600; font-size:.85rem; }
.knapp:hover { background:var(--bg); }
.nb { white-space:nowrap; }
@media (max-width: 360px) { main { padding:10px; } .kort { padding:12px; }
  table { font-size:.8rem; } th, td { padding:6px 2px; } .knapp { padding:3px 7px; } }
.knapp.stor { padding:8px 14px; font-size:.95rem; }
"""


def _hittil(ctx: dict[str, Any]) -> str:
    h = ctx.get("hittil")
    if h and h.get("kwh") is not None:
        kwh = f"{fmt_kwh(h['kwh'])} kWh"
    else:
        kwh = "–"
    snitt = f"{fmt_tall(h['snitt'], 4)} kr/kWh" if h and h.get("snitt") is not None else "–"
    kr = f"{fmt_tall(h['kr'], 2)} kr" if h and h.get("kr") is not None else "–"
    est = ctx.get("estimat")
    if est:
        estimat = (
            f"<p>Anslått for hele måneden: <strong>ca. {fmt_tall(est['kwh'], 0)} kWh / "
            f"ca. {fmt_tall(est['kr'], 0)} kr</strong></p>"
        )
    else:
        estimat = ""
    return f"""
<section class="kort">
  <h2>Denne måneden – hittil</h2>
  <div class="tre">
    <div><div class="tall">{kwh}</div><div class="tekst">Forbruk</div></div>
    <div><div class="tall">{snitt}</div><div class="tekst">Snittpris hittil</div></div>
    <div><div class="tall">{kr}</div><div class="tekst">Kostnad hittil</div></div>
  </div>
  <p class="liten">Snittpris og kostnad er høyere tidlig i måneden fordi de faste leddene
  fordeles på få kWh. Utover måneden synker snittprisen.</p>
  {estimat}
  <p class="liten">Oppdatert {_tidspunkt(ctx["oppdatert"])}</p>
</section>"""


def _historikk(synlige: list[dict[str, Any]], ubetalt_sum: float, pdf_base: str | None) -> str:
    if not synlige:
        return """
<section class="kort">
  <h2>Historikk</h2>
  <p>Ingen oppgjør ennå.</p>
</section>"""

    def periodecelle(p: dict[str, Any]) -> str:
        tekst = _e(periode_tekst(p))
        if not pdf_base:
            return tekst
        href = _e(f"{pdf_base}/{fakturanavn(p['id'])}")
        # lenken ligger under periodenavnet, så den alltid er synlig, også på smale skjermer
        return (
            f'{tekst}<br><a class="knapp" href="{href}" '
            f'aria-label="Last ned fakturagrunnlag for {_e(maaned_tekst(p["id"]))} som PDF">'
            "Last ned PDF</a>"
        )

    rader = "\n".join(
        f"""      <tr>
        <td>{periodecelle(p)}</td>
        <td><span class="nb">{fmt_kwh(p["leilighet_kwh"])} kWh</span><br><span class="liten">× {fmt_tall(p["snitt"], 4)} kr/kWh</span></td>
        <td>{fmt_tall(p["belop"], 2)}</td>
        <td><span class="nb">{_status_tekst(p["status"])}</span><br><span class="liten">forfall {fmt_dato(p["forfall"])}</span></td>
      </tr>"""
        for p in synlige
    )
    regnskap = ""
    if pdf_base:
        href = _e(f"{pdf_base}/{REGNSKAPSNAVN}")
        regnskap = (
            f'\n  <p><a class="knapp stor" href="{href}">Last ned hele regnskapet (PDF)</a></p>'
        )
    return f"""
<section class="kort">
  <h2>Historikk</h2>
  <div class="rull">
  <table>
    <thead><tr><th>Periode</th><th>Forbruk og pris</th><th>Beløp (kr)</th><th>Status</th></tr></thead>
    <tbody>
{rader}
    </tbody>
    <tfoot><tr><td colspan="2">Totalt utestående</td><td>{fmt_tall(ubetalt_sum, 2)}</td><td></td></tr></tfoot>
  </table>
  </div>{regnskap}
</section>"""


def _utregning(siste: dict[str, Any] | None) -> str:
    hus = ""
    if siste:
        hus = f"""
  <p>Husets tall for <strong>{_e(maaned_tekst(siste["id"]))}</strong>:</p>
  <dl>
    <dt>Husets forbruk</dt><dd>{fmt_tall(siste["hus_kwh"], 2)} kWh</dd>
    <dt>Kraft</dt><dd>{fmt_tall(siste["kraft"], 2)} kr</dd>
    <dt>Nettleie</dt><dd>{fmt_tall(siste["nettleie"], 2)} kr</dd>
    <dt>Norgespris (fratrekk)</dt><dd>{fmt_tall(siste["norgespris"], 2)} kr</dd>
    <dt>Sum</dt><dd>{fmt_tall(siste["sum"], 2)} kr</dd>
    <dt>Snittpris</dt><dd>{fmt_tall(siste["snitt"], 4)} kr/kWh</dd>
  </dl>"""
    return f"""
<section class="kort">
<details>
  <summary>Slik er beløpet regnet ut</summary>
  <p>Beløpet er ditt målte strømforbruk (kWh) multiplisert med husets faktiske snittpris
  for samme kalendermåned.</p>
  <p>Husets snittpris er kraft pluss nettleie minus Norgespris, delt på husets samlede kWh.
  Alle ledd er med, inkludert mva og faste ledd.</p>{hus}
</details>
</section>"""


def render_side(ctx: dict[str, Any]) -> str:
    """Bygger hele HTML-siden fra kontekst-dicten (se tests/data.py for formen)."""
    lt = ctx["leietaker"]
    ul = ctx["utleier"]
    synlige = sorted(
        (p for p in ctx["perioder"] if p["status"] != STATUS_VENTER),
        key=lambda p: p["id"],
        reverse=True,
    )
    ubetalt = utestaaende(synlige)
    merke = (
        '<span class="merke ubetalt">Ikke betalt</span>'
        if ubetalt > 0
        else '<span class="merke ok">Betalt</span>'
    )
    siste = synlige[0] if synlige else None
    merking = f"Strøm – {maaned_tekst(siste['id'])}" if siste else "Strøm"
    innflyttet = fmt_dato(lt["innflyttet"]) if lt.get("innflyttet") else "–"

    return f"""<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Strømregnskap · {_e(lt["adresse"])}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>Strømregnskap · leietaker</h1>
<p class="sub">{_e(lt["adresse"])}<br>
Leietaker: {_e(lt["navn"])} · Utleier: {_e(ul["navn"])}<br>
Leieforhold fra {innflyttet}</p>

<section class="kort">
  <h2>Utestående nå {merke}</h2>
  <div class="stor">{fmt_tall(ubetalt, 2)} kr</div>
</section>

<section class="kort">
  <h2>Betaling</h2>
  <dl>
    <dt>Kontonummer</dt><dd>{_e(ul["kontonummer"])}</dd>
    <dt>Til</dt><dd>{_e(ul["navn"])}</dd>
    <dt>Merking</dt><dd>{_e(merking)}</dd>
    <dt>Frist</dt><dd>Den {_e(ctx["forfallsdag"])}. hver måned</dd>
  </dl>
</section>
{_hittil(ctx)}
{_historikk(synlige, ubetalt, ctx.get("pdf_base"))}
{_utregning(siste)}
<p class="liten">Generert av Home Assistant {_tidspunkt(ctx["oppdatert"])}</p>
</main>
</body>
</html>
"""
