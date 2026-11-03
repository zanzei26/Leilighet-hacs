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


def bygg_epost(
    *,
    periode: dict[str, Any],
    leietaker: dict[str, Any],
    utleier: dict[str, Any],
    side_url: str | None,
    cc_utleier: bool = True,
) -> EmailMessage:
    """Bygger månedsoppgjøret som flerdelt e-post (ren tekst + HTML)."""
    maaned = maaned_tekst(periode["id"])
    fornavn = _fornavn(leietaker["navn"])
    kwh = f"{fmt_kwh(periode['leilighet_kwh'])} kWh"
    snitt = f"{fmt_tall(periode['snitt'], 4)} kr/kWh"
    belop = f"{fmt_tall(periode['belop'], 2)} kr"
    forfall = fmt_dato(periode["forfall"])
    merking = f"Strøm – {maaned}"
    konto = utleier["kontonummer"]

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

Ditt forbruk: {kwh}
Husets snittpris: {snitt}
Beløp å betale: {belop}
Forfall: {forfall}

Betal til kontonummer {konto} og merk betalingen «{merking}».

{avsnitt_tekst}
Hilsen
{utleier["navn"]}
"""

    e = escape
    html = f"""<!doctype html>
<html lang="nb"><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5;color:#1b1f24">
<p>Hei {e(fornavn)},</p>
<p>Her er strømoppgjøret for <strong>{e(maaned)}</strong>.</p>
<table style="border-collapse:collapse">
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Ditt forbruk</td><td><strong>{e(kwh)}</strong></td></tr>
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Husets snittpris</td><td><strong>{e(snitt)}</strong></td></tr>
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Beløp å betale</td><td><strong>{e(belop)}</strong></td></tr>
<tr><td style="padding:2px 16px 2px 0;color:#5c6670">Forfall</td><td><strong>{e(forfall)}</strong></td></tr>
</table>
<p>Betal til kontonummer <strong>{e(konto)}</strong> og merk betalingen «{e(merking)}».</p>
{avsnitt_html}
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
