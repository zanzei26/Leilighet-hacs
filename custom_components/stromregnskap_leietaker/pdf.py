"""Minimal PDF-skriver uten eksterne avhengigheter.

Kan tegne tekst (Helvetica og Helvetica-Bold, WinAnsi), linjer og fylte rektangler på
A4-sider, og legger på bunntekst og «Side n av m». Det er nok til fakturagrunnlag og regnskap,
og det betyr at eksport aldri kan stoppe fordi et bibliotek ikke lot seg installere.

Koordinater er i punkter fra øvre venstre hjørne (y vokser nedover). Teksten plasseres på
grunnlinjen.
"""

from __future__ import annotations

import zlib
from datetime import datetime

from .pdf_metrikk import FØRSTE_KODE, HELVETICA, HELVETICA_FET, STANDARDBREDDE

A4_BREDDE = 595.28
A4_HOYDE = 841.89
PRODUSENT = "Strømregnskap leietaker"

Farge = tuple[float, float, float]
SVART: Farge = (0.0, 0.0, 0.0)
GRAA: Farge = (0.4, 0.4, 0.4)
LYS_GRAA: Farge = (0.93, 0.93, 0.93)
LINJEFARGE: Farge = (0.7, 0.7, 0.7)


def tekstbredde(tekst: str, storrelse: float, fet: bool = False) -> float:
    """Bredden på teksten i punkter."""
    tabell = HELVETICA_FET if fet else HELVETICA
    total = 0
    for byte in tekst.encode("cp1252", errors="replace"):
        i = byte - FØRSTE_KODE
        total += tabell[i] if 0 <= i < len(tabell) else STANDARDBREDDE
    return total * storrelse / 1000


def _tall(v: float) -> str:
    """Tall med inntil to desimaler og uten overflødige nuller (PDF vil ha punktum)."""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _farge(f: Farge) -> str:
    return " ".join(_tall(k) for k in f)


def _streng(tekst: str) -> bytes:
    """PDF-literal i cp1252 med escape av (, ) og \\. Linjeskift blir mellomrom."""
    byte = tekst.replace("\r", " ").replace("\n", " ").encode("cp1252", errors="replace")
    byte = byte.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"(" + byte + b")"


def _utf16_hex(tekst: str) -> bytes:
    return b"<FEFF" + tekst.encode("utf-16-be").hex().upper().encode("ascii") + b">"


def _pdf_dato(tidspunkt: datetime) -> bytes:
    grunn = tidspunkt.strftime("D:%Y%m%d%H%M%S")
    forskyvning = tidspunkt.utcoffset()
    if forskyvning is None:
        return f"({grunn}Z)".encode("ascii")
    minutter = int(forskyvning.total_seconds() // 60)
    tegn = "+" if minutter >= 0 else "-"
    t, m = divmod(abs(minutter), 60)
    return f"({grunn}{tegn}{t:02d}'{m:02d}')".encode("ascii")


class Side:
    """En A4-side. Tegneoperasjonene samles og skrives når dokumentet lages."""

    def __init__(self) -> None:
        self._ops: list[bytes] = []

    def tekst(
        self,
        x: float,
        y: float,
        tekst: str,
        *,
        storrelse: float = 10.0,
        fet: bool = False,
        farge: Farge = SVART,
        hoyre: bool = False,
        midt: bool = False,
    ) -> None:
        """Tegner tekst med grunnlinje i y. ``hoyre``: x er høyre kant. ``midt``: x er midten."""
        bredde = tekstbredde(tekst, storrelse, fet)
        if hoyre:
            x -= bredde
        elif midt:
            x -= bredde / 2
        font = b"/F2" if fet else b"/F1"
        self._ops.append(
            b"BT\n"
            + font
            + f" {_tall(storrelse)} Tf\n{_farge(farge)} rg\n".encode("ascii")
            + f"1 0 0 1 {x:.2f} {A4_HOYDE - y:.2f} Tm\n".encode("ascii")
            + _streng(tekst)
            + b" Tj\nET"
        )

    def linje(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        bredde: float = 0.5,
        farge: Farge = LINJEFARGE,
    ) -> None:
        self._ops.append(
            f"{_tall(bredde)} w\n{_farge(farge)} RG\n"
            f"{x1:.2f} {A4_HOYDE - y1:.2f} m\n{x2:.2f} {A4_HOYDE - y2:.2f} l\nS".encode("ascii")
        )

    def rektangel(
        self, x: float, y: float, bredde: float, hoyde: float, *, fyll: Farge = LYS_GRAA
    ) -> None:
        """Fylt rektangel med øvre venstre hjørne i (x, y)."""
        y_pdf = A4_HOYDE - y - hoyde
        self._ops.append(
            (f"{_farge(fyll)} rg\n{x:.2f} {y_pdf:.2f} {bredde:.2f} {hoyde:.2f} re\nf").encode(
                "ascii"
            )
        )

    def innhold(self) -> bytes:
        return b"\n".join(self._ops)


class Dokument:
    """Et PDF-dokument av A4-sider."""

    def __init__(self, tittel: str, bunntekst: str = "") -> None:
        self.tittel = tittel
        self.bunntekst = bunntekst
        self.sider: list[Side] = []

    def ny_side(self) -> Side:
        side = Side()
        self.sider.append(side)
        return side

    def til_bytes(self, tidspunkt: datetime) -> bytes:
        sider = self.sider or [Side()]
        antall = len(sider)

        objekter: list[bytes] = []  # objekt n ligger på indeks n - 1

        def legg(innhold: bytes) -> int:
            objekter.append(innhold)
            return len(objekter)

        # 1: katalog, 2: sider (fylles etterpå), 3-4: fonter
        legg(b"")
        legg(b"")
        legg(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        legg(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )

        sidenr: list[int] = []
        for nr, side in enumerate(sider, start=1):
            bunn = Side()
            if self.bunntekst:
                bunn.tekst(50, A4_HOYDE - 28, self.bunntekst, storrelse=8, farge=GRAA)
            bunn.tekst(
                A4_BREDDE - 50,
                A4_HOYDE - 28,
                f"Side {nr} av {antall}",
                storrelse=8,
                farge=GRAA,
                hoyre=True,
            )
            data = zlib.compress(side.innhold() + b"\n" + bunn.innhold())
            strom = legg(
                f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n".encode("ascii")
                + data
                + b"\nendstream"
            )
            sidenr.append(
                legg(
                    (
                        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4_BREDDE} {A4_HOYDE}] "
                        f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {strom} 0 R >>"
                    ).encode("ascii")
                )
            )

        info = legg(
            b"<< /Title "
            + _utf16_hex(self.tittel)
            + b" /Producer "
            + _utf16_hex(PRODUSENT)
            + b" /CreationDate "
            + _pdf_dato(tidspunkt)
            + b" >>"
        )
        kids = " ".join(f"{n} 0 R" for n in sidenr)
        objekter[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objekter[1] = f"<< /Type /Pages /Kids [{kids}] /Count {antall} >>".encode("ascii")

        ut = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        forskyvninger: list[int] = []
        for nr, innhold in enumerate(objekter, start=1):
            forskyvninger.append(len(ut))
            ut += f"{nr} 0 obj\n".encode("ascii") + innhold + b"\nendobj\n"
        xref = len(ut)
        ut += f"xref\n0 {len(objekter) + 1}\n".encode("ascii")
        ut += b"0000000000 65535 f \n"
        for forskyvning in forskyvninger:
            ut += f"{forskyvning:010d} 00000 n \n".encode("ascii")
        ut += (
            f"trailer\n<< /Size {len(objekter) + 1} /Root 1 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
        return bytes(ut)
