# Endringslogg

## 0.4.7
- Prisen i månedsanslaget er husets forventede snittpris for måneden (husets kostnadsprognose ÷ forventet kWh) når den finnes og ligger innenfor grensene for snittpris, ellers forrige periodes snitt som før. De tre første døgnene brukes fortsatt forrige periodes snitt. Ny valgfri innstilling «Husets kostnadsprognose» (standard `sensor.jarvis_stromkostnad_prognose`, attributtet `kwh_prognose`), som kan tømmes. Nye attributter `estimat_pris` og `estimat_pris_kilde` (`husets_prognose` / `forrige_periode`), og siden forklarer hvilken pris som er brukt. Bare visning: oppgjør, e-post, PDF og sperre er uendret.

## 0.4.6
- Månedsestimatet bygger på leilighetens egen takt (forbruk hittil fra måleren ÷ medgått tid × månedens lengde, i timer) fra og med 72 timer ut i måneden. De tre første døgnene, og uten målerstand ved månedsskiftet, brukes forrige periode × husets endring som før. Prisen er forrige periodes snitt. Nytt attributt `estimat_metode` (`takt`, `forrige_periode`, `ingen`). Bare visning: oppgjør, e-post, PDF og sperre er uendret.

Eldre versjoner: se commit-meldingene.
