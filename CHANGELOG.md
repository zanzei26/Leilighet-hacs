# Endringslogg

## 0.4.6
- Månedsestimatet bygger på leilighetens egen takt (forbruk hittil fra måleren ÷ medgått tid × månedens lengde, i timer) fra og med 72 timer ut i måneden. De tre første døgnene, og uten målerstand ved månedsskiftet, brukes forrige periode × husets endring som før. Prisen er forrige periodes snitt. Nytt attributt `estimat_metode` (`takt`, `forrige_periode`, `ingen`). Bare visning: oppgjør, e-post, PDF og sperre er uendret.

Eldre versjoner: se commit-meldingene.
