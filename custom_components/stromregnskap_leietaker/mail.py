"""Bygging og sending av e-post til leietaker (Gmail SMTP med app-passord).

Bruker bare standardbiblioteket (smtplib/email). ``send_epost`` og ``sjekk_smtp``
blokkerer og skal kjøres i executor.
"""

from __future__ import annotations

import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage
from html import escape
from typing import Any

from .calc import har_lader, leilighet_belop
from .page import fmt_dato, fmt_kwh, fmt_tall, maaned_tekst

SMTP_TIMEOUT = 30


class SmtpFeil(Exception):
    """Feil ved SMTP. ``kind`` er «auth», «connect» eller «send»."""

    def __init__(self, kind: str, melding: str) -> None:
        super().__init__(melding)
        self.kind = kind


def _adresse(navn: str, epost: str) -> Address:
    return Address(display_name=navn, addr_spec=epost)


def _fornavn(navn: str) -> str:
    deler = navn.split()
    return deler[0] if deler else ""


def _gate(adresse: str) -> str:
    """«Testveien 1, 1. etasje» → «Testveien 1»."""
    return adresse.split(",")[0].strip()


def _legg_ved(msg: EmailMessage, vedlegg: list[tuple[str, str, bytes]]) -> None:
    """Legger vedlegg på som (filnavn, mimetype, innhold)."""
    for navn, mimetype, innhold in vedlegg:
        hovedtype, _, undertype = mimetype.partition("/")
        msg.add_attachment(innhold, maintype=hovedtype, subtype=undertype, filename=navn)


def bygg_epost(
    *,
    periode: dict[str, Any],
    leietaker: dict[str, Any],
    utleier: dict[str, Any],
    side_url: str | None,
    cc_utleier: bool = True,
    vedlegg: list[tuple[str, str, bytes]] | None = None,
) -> EmailMessage:
    """Bygger månedsoppgjøret som flerdelt e-post (ren tekst + HTML), evt. med regningen vedlagt."""
    maaned = maaned_tekst(periode["id"])
    fornavn = _fornavn(leietaker["navn"])
    kwh = f"{fmt_kwh(periode['leilighet_kwh'])} kWh"
    snitt = f"{fmt_tall(periode['snitt'], 4)} kr/kWh"
    belop = f"{fmt_tall(periode['belop'], 2)} kr"
    forfall = fmt_dato(periode["forfall"])
    merking = f"Strøm – {maaned}"
    konto = utleier["kontonummer"]
    # elbil-lader (valgfri): egne linjer, og beløpet delt i leilighet og lader
    lader_forbruk = lader_belop = ""
    lader_forbruk_html = lader_belop_html = ""
    if har_lader(periode):
        lader_kwh = f"{fmt_kwh(periode['lader_kwh'])} kWh"
        b_leil = f"{fmt_tall(leilighet_belop(periode), 2)} kr"
        b_lader = f"{fmt_tall(periode['lader_belop'], 2)} kr"
        lader_forbruk = f"\nElbil-lader: {lader_kwh}"
        lader_belop = f"\nBeløp leilighet: {b_leil}\nBeløp elbil-lader: {b_lader}"
        rad = '<tr><td style="padding:2px 16px 2px 0;color:#5c6670">{}</td><td><strong>{}</strong></td></tr>'
        lader_forbruk_html = "\n" + rad.format("Elbil-lader", escape(lader_kwh))
        lader_belop_html = (
            "\n"
            + rad.format("Beløp leilighet", escape(b_leil))
            + "\n"
            + rad.format("Beløp elbil-lader", escape(b_lader))
        )

    vedlagt = "Regningen er vedlagt som PDF."
    vedlagt_tekst = f"{vedlagt}\n\n" if vedlegg else ""
    vedlagt_html = f"<p>{vedlagt}</p>\n" if vedlegg else ""

    forklaring = (
        "Beløpet er ditt målte forbruk multiplisert med husets faktiske snittpris for måneden."
    )
    if side_url:
        avsnitt_tekst = f"{forklaring}\nFull utregning og historikk finner du her:\n{side_url}\n"
        avsnitt_html = (
            f"<p>{forklaring}\n"
            f'Full utregning og historikk finner du <a href="{escape(side_url, quote=True)}">her</a>:'
            f'<br>\n<a href="{escape(side_url, quote=True)}">{escape(side_url)}</a></p>'
        )
    else:
        avsnitt_tekst = f"{forklaring}\n"
        avsnitt_html = f"<p>{forklaring}</p>"

    tekst = f"""Hei {fornavn},

Her er strømoppgjøret for {maaned}.

Ditt forbruk: {kwh}{lader_forbruk}
Husets snittpris: {snitt}{lader_belop}
Beløp å betale: {belop}
Forfall: {forfall}

Betal til kontonummer {konto} og merk betalingen «{merking}».

{vedlagt_tekst}{avsnitt_tekst}
Hilsen
{utleier["navn"]}
"""

    e = escape
    html = f"""<!doctype html>
<html lang="nb"><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5;color:#1b1f24">
<p>Hei {e(fornavn)},</p>
<p>Her er strømoppgjøret for <strong>{e(maaned)}</strong>.</p>
<table style="border-collapse:collapse">
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Ditt forbruk</td><td><strong>{e(kwh)}</strong></td></tr>{lader_forbruk_html}
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Husets snittpris</td><td><strong>{e(snitt)}</strong></td></tr>{lader_belop_html}
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Beløp å betale</td><td><strong>{e(belop)}</strong></td></tr>
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Forfall</td><td><strong>{e(forfall)}</strong></td></tr>
</table>
<p>Betal til kontonummer <strong>{e(konto)}</strong> og merk betalingen «{e(merking)}».</p>
{vedlagt_html}{avsnitt_html}
<p>Hilsen<br>{e(utleier["navn"])}</p>
</body></html>
"""

    msg = EmailMessage()
    msg["Subject"] = f"Strømoppgjør {maaned} – {_gate(leietaker['adresse'])}"
    msg["From"] = _adresse(utleier["navn"], utleier["epost"])
    msg["To"] = _adresse(leietaker["navn"], leietaker["epost"])
    if cc_utleier:
        msg["Cc"] = _adresse(utleier["navn"], utleier["epost"])
    msg.set_content(tekst)
    msg.add_alternative(html, subtype="html")
    if vedlegg:
        _legg_ved(msg, vedlegg)
    return msg


def bygg_fakturapost(
    *,
    periode: dict[str, Any],
    leietaker: dict[str, Any],
    utleier: dict[str, Any],
    side_url: str,
    vedlegg: list[tuple[str, str, bytes]],
    cc_utleier: bool = True,
) -> EmailMessage:
    """E-post med lenken til leietakersiden og regningen for en periode som PDF-vedlegg."""
    maaned = maaned_tekst(periode["id"])
    fornavn = _fornavn(leietaker["navn"])
    belop = f"{fmt_tall(periode['belop'], 2)} kr"
    forfall = fmt_dato(periode["forfall"])
    merking = f"Strøm – {maaned}"
    konto = utleier["kontonummer"]
    vedlagt = f"Regningen for {maaned} er vedlagt som PDF."
    regnskap = (
        "Hele regnskapet er løpende tilgjengelig på siden, og du kan laste det ned som PDF hvis "
        "du ønsker det. Forbruket for inneværende måned er live på siden, så du kan følge med "
        "på det hvis du vil."
    )
    advarsel = "Lenken er personlig. Ikke del den med andre. Legg den gjerne som bokmerke."
    tekst = f"""Hei {fornavn},

Her er ny lenke til den oppdaterte siden din med betalingsinformasjon:

{side_url}

{vedlagt}

Beløp å betale: {belop}
Forfall: {forfall}

Betal til kontonummer {konto} og merk betalingen «{merking}».

{regnskap}

{advarsel}

Hilsen
{utleier["navn"]}
"""
    e = escape
    html = f"""<!doctype html>
<html lang="nb"><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5;color:#1b1f24">
<p>Hei {e(fornavn)},</p>
<p>Her er ny lenke til den oppdaterte siden din med betalingsinformasjon:</p>
<p><a href="{e(side_url, quote=True)}">{e(side_url)}</a></p>
<p>{e(vedlagt)}</p>
<table style="border-collapse:collapse">
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Beløp å betale</td><td><strong>{e(belop)}</strong></td></tr>
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Forfall</td><td><strong>{e(forfall)}</strong></td></tr>
</table>
<p>Betal til kontonummer <strong>{e(konto)}</strong> og merk betalingen «{e(merking)}».</p>
<p>{e(regnskap)}</p>
<p>{e(advarsel)}</p>
<p>Hilsen<br>{e(utleier["navn"])}</p>
</body></html>
"""
    msg = EmailMessage()
    msg["Subject"] = f"Strømregning {maaned} – {_gate(leietaker['adresse'])}"
    msg["From"] = _adresse(utleier["navn"], utleier["epost"])
    msg["To"] = _adresse(leietaker["navn"], leietaker["epost"])
    if cc_utleier:
        msg["Cc"] = _adresse(utleier["navn"], utleier["epost"])
    msg.set_content(tekst)
    msg.add_alternative(html, subtype="html")
    _legg_ved(msg, vedlegg)
    return msg


def bygg_lenkepost(
    *,
    leietaker: dict[str, Any],
    utleier: dict[str, Any],
    side_url: str,
    cc_utleier: bool = True,
) -> EmailMessage:
    """Kort e-post med bare lenken til leietakersiden."""
    fornavn = _fornavn(leietaker["navn"])
    forklaring = (
        "Der ser du alltid hva som er utestående, forbruket ditt hittil denne måneden og "
        "historikken for tidligere måneder, med forfall og hvor du betaler. "
        "Siden oppdateres automatisk."
    )
    advarsel = "Lenken er personlig. Ikke del den med andre. Legg den gjerne som bokmerke."
    tekst = f"""Hei {fornavn},

Her er lenken til siden din for strømoppgjør:

{side_url}

{forklaring}

{advarsel}

Hilsen
{utleier["navn"]}
"""
    e = escape
    html = f"""<!doctype html>
<html lang="nb"><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5;color:#1b1f24">
<p>Hei {e(fornavn)},</p>
<p>Her er lenken til siden din for strømoppgjør:</p>
<p><a href="{e(side_url, quote=True)}">{e(side_url)}</a></p>
<p>{e(forklaring)}</p>
<p>{e(advarsel)}</p>
<p>Hilsen<br>{e(utleier["navn"])}</p>
</body></html>
"""
    msg = EmailMessage()
    msg["Subject"] = f"Din side for strømoppgjør – {_gate(leietaker['adresse'])}"
    msg["From"] = _adresse(utleier["navn"], utleier["epost"])
    msg["To"] = _adresse(leietaker["navn"], leietaker["epost"])
    if cc_utleier:
        msg["Cc"] = _adresse(utleier["navn"], utleier["epost"])
    msg.set_content(tekst)
    msg.add_alternative(html, subtype="html")
    return msg


def bygg_kopipost(
    *,
    periode: dict[str, Any],
    leietaker: dict[str, Any],
    utleier: dict[str, Any],
    vedlegg: list[tuple[str, str, bytes]],
) -> EmailMessage:
    """Kopi til utleier etter et oppgjør, med vedlegg som (filnavn, mimetype, innhold).

    Er ment som en kopi utenfor Home Assistant: fakturagrunnlag, hele regnskapet og en
    JSON-sikkerhetskopi av alle data.
    """
    maaned = maaned_tekst(periode["id"])
    liste = "\n".join(f"- {navn}" for navn, _, _ in vedlegg)
    lader = ""
    if har_lader(periode):
        lader = (
            f"\nElbil-lader: {fmt_kwh(periode['lader_kwh'])} kWh × "
            f"{fmt_tall(periode['snitt'], 4)} kr/kWh = {fmt_tall(periode['lader_belop'], 2)} kr"
        )
    tekst = f"""Hei {_fornavn(utleier["navn"])},

Dette er en kopi til deg som utleier. Oppgjøret for {maaned} er laget og sendt til \
{leietaker["navn"]} ({leietaker["epost"]}).

Beløp: {fmt_tall(periode["belop"], 2)} kr
Forbruk: {fmt_kwh(periode["leilighet_kwh"])} kWh × {fmt_tall(periode["snitt"], 4)} kr/kWh{lader}
Forfall: {fmt_dato(periode["forfall"])}

Vedlagt:
{liste}

Sikkerhetskopien (JSON) inneholder alle perioder, målerstander og øyeblikksbilder.
Ta vare på denne e-posten. Den er en kopi som ligger utenfor Home Assistant.
"""
    msg = EmailMessage()
    msg["Subject"] = f"Fakturagrunnlag strøm leilighet – {maaned}"
    msg["From"] = _adresse(utleier["navn"], utleier["epost"])
    msg["To"] = _adresse(utleier["navn"], utleier["epost"])
    msg.set_content(tekst)
    _legg_ved(msg, vedlegg)
    return msg


def bygg_testepost(utleier: dict[str, Any]) -> EmailMessage:
    """Liten test-e-post til utleier, brukt av oppsettsflyten."""
    msg = EmailMessage()
    msg["Subject"] = "Test fra Strømregnskap leietaker"
    msg["From"] = _adresse(utleier["navn"], utleier["epost"])
    msg["To"] = _adresse(utleier["navn"], utleier["epost"])
    msg.set_content(
        "Dette er en test fra integrasjonen «Strømregnskap leietaker».\n"
        "Hvis du leser dette fungerer SMTP-oppsettet.\n"
    )
    return msg


def _kjor(
    host: str, port: int, brukernavn: str, passord: str, melding: EmailMessage | None
) -> None:
    """Logger inn (STARTTLS) og sender eventuelt meldingen. Blokkerende."""
    try:
        kontekst = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as smtp:
            smtp.starttls(context=kontekst)
            smtp.login(brukernavn, passord)
            if melding is not None:
                smtp.send_message(melding)
    except smtplib.SMTPAuthenticationError as err:
        raise SmtpFeil("auth", "Innlogging avvist av SMTP-serveren") from err
    except (
        smtplib.SMTPRecipientsRefused,
        smtplib.SMTPSenderRefused,
        smtplib.SMTPDataError,
    ) as err:
        raise SmtpFeil("send", f"SMTP-serveren avviste meldingen ({type(err).__name__})") from err
    except (smtplib.SMTPException, OSError, TimeoutError) as err:
        raise SmtpFeil("connect", f"Kunne ikke nå SMTP-serveren ({type(err).__name__})") from err


def send_epost(
    *, host: str, port: int, brukernavn: str, passord: str, melding: EmailMessage
) -> None:
    """Sender én melding. Til/Cc leses fra meldingens egne headere."""
    _kjor(host, port, brukernavn, passord, melding)


def sjekk_smtp(
    *,
    host: str,
    port: int,
    brukernavn: str,
    passord: str,
    testmelding: EmailMessage | None = None,
) -> None:
    """Verifiserer innlogging, og sender eventuelt en testmelding."""
    _kjor(host, port, brukernavn, passord, testmelding)
