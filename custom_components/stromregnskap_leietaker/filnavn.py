"""Filnavn på PDF-ene, delt mellom siden, dokumentene og nedlastingsruten."""

REGNSKAPSNAVN = "regnskap-strom-leilighet.pdf"


def fakturanavn(periode_id: str) -> str:
    return f"fakturagrunnlag-strom-leilighet-{periode_id}.pdf"
