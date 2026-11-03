# Strømregnskap leietaker

Custom integration for Home Assistant som regner ut leietakers månedlige strømoppgjør, lagrer historikk, publiserer en leietakerside, sender e-post til leietaker og varsler utleier hvis noe ser galt ut. Installeres via HACS.

**Metode (fra leiekontrakten):** leietaker betaler eget målt forbruk (kWh) × husets faktiske snittpris for samme kalendermåned (kraft + nettleie − Norgespris, alle ledd inkl. mva og faste ledd, delt på husets kWh). Forfall er den 15. i måneden etter.

> **Status: versjon 0.1.0.** Testet med `pytest-homeassistant-custom-component` mot Home Assistant 2026.2.3 (192 tester, SMTP er mocket). Den er ikke kjørt mot en ekte HA-instans eller mot ekte Gmail ennå. Se [Åpne punkter](#åpne-punkter).

## Krav

- Home Assistant 2026.2 eller nyere
- HACS
- Disse sensorene finnes allerede (entity-ID-ene kan endres i oppsettet):

| Standard entity-ID | Hva den brukes til |
|---|---|
| `sensor.jarvis_stromregnskap` | Husets månedstall. Attributtene `maneder` og `denne_maneden`. Eneste kilde til husets snittpris. |
| `sensor.leilighet_strom_denne_maneden` | Leilighetens forbruk i løpende måned (utility_meter). `last_period` er forrige måneds sluttverdi. |
| `sensor.minusmaler_leilighet_import` | Rå akkumulert kWh. Eksponeres som attributt, brukes ikke i beregningen. |
| `sensor.minusmaler_leilighet_effekt` | Øyeblikkseffekt (W), kun til visning. |
| `sensor.mal_forbruk_prognose` | Attributtet `endring_prosent` brukes til månedsestimatet. |
| `notify.varsle_magnar` | Varslingstjeneste til utleier (en tjeneste, ikke en entitet). |

## Installasjon

1. HACS → ⋮ → **Egendefinerte repositories** → legg til `https://github.com/zanzei26/Leilighet-hacs` som kategori **Integration**.
2. Installer «Strømregnskap leietaker» og start Home Assistant på nytt.
3. **Innstillinger → Enheter og tjenester → Legg til integrasjon → Strømregnskap leietaker.**

## Oppsett (UI)

1. **Leietaker og utleier:** navn, e-post, adresse, innflyttingsdato, utleiers navn og e-post, kontonummer, forfallsdag (standard 15).
2. **Datakilder:** de fem sensorene og varslingstjenesten.
3. **E-post (SMTP):** server (standard `smtp.gmail.com`), port (587), brukernavn, app-passord. Innloggingen testes før du kommer videre, og du kan la den sende en test-e-post til utleier. Kopi til utleier er på som standard.
4. **Leietakerside:** på/av. Lenken vises i skjemaet.
5. **Rimelighetskontroll og kjøretid:** snittpris min 0,50 / maks 3,00 kr/kWh, maks ±60 % endring i kWh mot forrige periode, kjøring den 3. kl. 08:00 og sjekk til og med den 6.
6. **Eksisterende historikk:** importerer september (30.08–30.09) og oktober 2026 slik de er fakturert.

Alt kan endres senere under **Konfigurer** (menyvalg per tema). Passordfeltet kan stå tomt for å beholde gjeldende app-passord. App-passordet lagres i oppsettet uten kryptering (Home Assistant krypterer ikke config entries).

## Slik fungerer månedsoppgjøret

Koordinatoren kjører hver time. Fra kjøredagen kl. 08:00 til og med siste sjekkdag prøver den å lage oppgjør for forrige kalendermåned, hvis det ikke finnes fra før:

1. `sensor.jarvis_stromregnskap` må ha et element i `maneder` med riktig `mnd` og komplette tall for huset. Ellers prøves det igjen hver time. På siste sjekkdag kl. 08:00 får utleier ett varsel og en Repairs-melding.
2. Leilighetens kWh er primært `leilighet_kwh` fra `maneder`, ellers `last_period` fra utility_meter. Er begge til stede og avviker de mer enn 0,5 kWh, sendes ikke oppgjøret. Utleier får begge tallene.
3. Beløp = kWh × snittpris, avrundet til hele øre (halvt øre rundes opp).
4. **Rimelighetskontroll** (snittpris innenfor grensene, 0 < leilighet ≤ hus, endring mot forrige periode innenfor grensen). Ved brudd får perioden status `venter_godkjenning`, utleier får varsel med tallene og hvilken regel som slo ut, og en Repairs-melding med «Godkjenn». Ingenting sendes, og perioden vises ikke på siden.
5. Ellers lagres perioden, siden oppdateres, og e-post sendes (kopi til utleier). Utleier får et kort push-varsel.
6. Feiler e-posten, beholdes perioden og det prøves igjen hver time i 48 timer. Utleier varsles én gang, og deretter kommer en Repairs-melding med «Send på nytt».

`ikke_betalt` blir automatisk `betalt` fra og med forfallsdagen. `unntak_ikke_betalt` forblir ubetalt til noen setter `betalt` (tillitsbasert, utleier sjekker nettbanken selv).

## Leietakersiden

Integrasjonen skriver én selvstendig HTML-fil (ingen JavaScript, ingen eksterne ressurser, `noindex`, lys/mørk modus) til `/config/www/<hemmelig-slug>/index.html` hver time og ved alle endringer. Lenken er `https://<nabu-casa-id>.ui.nabu.casa/local/<slug>/index.html` (Nabu Casa først, ellers ekstern/intern URL).

Siden leveres av en egen rute på nøyaktig denne URL-en, og ikke av Home Assistants vanlige `/local`. Årsaken er at `/local` bare finnes hvis `www`-mappen fantes ved oppstart, og at den leverer filer med `Cache-Control: public, max-age=2678400` (31 dager), slik at leietakers nettleser kunne vist gamle tall i en måned. Ruten svarer uten innlogging med `Cache-Control: no-store`.

## Entiteter

| Entitet | Innhold |
|---|---|
| `sensor.leietaker_utestaende` | Sum ubetalt (kr). Attributter: antall perioder, lenke. |
| `sensor.leietaker_siste_oppgjor` | Beløp siste periode (kr). Attributter: alle feltene i perioden. |
| `sensor.leietaker_forbruk_hittil` | kWh denne måneden. Attributter: snittpris og kostnad hittil, estimat, `endring_prosent`, effekt (W), rå målerstand. |
| `sensor.leietaker_kostnad_hittil` | Kostnad hittil (kr). |
| `sensor.leietaker_estimat_maned` | Månedsestimat (kr). Attributt: kWh. |
| `sensor.leietaker_side_sist_publisert` | Tidsstempel. Attributt: lenke. |
| `binary_sensor.leietaker_oppgjor_venter_godkjenning` | `on` når en periode venter på godkjenning. |

Estimatet er forrige periodes leilighets-kWh × (1 + `endring_prosent`/100), priset til forrige periodes snittpris. «Hittil»-tall fra regnskapssensoren brukes bare når den faktisk viser inneværende måned.

## Tjenester

| Tjeneste | Felt | Gjør |
|---|---|---|
| `stromregnskap_leietaker.generer_oppgjor` | `periode` (ÅÅÅÅ-MM, standard forrige måned), `tving`, `send_epost` | Lager oppgjør manuelt. `tving` hopper over rimelighetskontrollen. |
| `stromregnskap_leietaker.godkjenn_oppgjor` | `periode` | Sender et oppgjør som venter på godkjenning. |
| `stromregnskap_leietaker.send_epost_pa_nytt` | `periode` | Sender e-posten på nytt. |
| `stromregnskap_leietaker.sett_status` | `periode`, `status` | `betalt`, `ikke_betalt` eller `unntak_ikke_betalt`. |
| `stromregnskap_leietaker.publiser_side` | | Lager siden på nytt nå. |
| `stromregnskap_leietaker.slett_periode` | `periode`, `bekreft: true` | Sletter en periode. Et sendt oppgjør er låst og kan bare fjernes slik. |
| `stromregnskap_leietaker.ny_leietaker` | | Leietakerskifte, se under. |

## Leietakerskifte

`ny_leietaker` arkiverer all historikk til `/config/stromregnskap_leietaker/arkiv/<navn>_<dato>.json`, tømmer historikken, bytter slug (ny lenke, og den gamle slutter å virke) og åpner rekonfigurering for de nye leietakeropplysningene. Rekonfigureringen åpnes fra ⋮-menyen på integrasjonen. Tjenesten starter også selve flyten og returnerer arkivfilen og den nye lenken.

## Datamodell

Lagres med Home Assistants `Store` (`stromregnskap_leietaker.<entry_id>`, versjonert med migrering). Hver periode har `id`, `start`, `slutt`, `leilighet_kwh`, `hus_kwh`, `kraft`, `nettleie`, `norgespris`, `sum`, `snitt`, `belop`, `forfall`, `status`, `generert`, `epost_sendt`, `kilde` og `notat`.

Tillegg utover den opprinnelige skissen:

- `epost_ventende_siden`: når utsendingsforsøkene startet (`null` når ingenting venter). Trengs for 48-timersgrensen, siden et godkjent oppgjør kan være dager gammelt.
- `tilstand.varslet`: nøkler for varsler som allerede er sendt, så de ikke gjentas hver time.
- `tilstand.historikk_importert`: hindrer at historikken importeres to ganger.

## Åpne punkter

Dette er avvik og ting som ikke er gjort. Det er viktig å se på dem før integrasjonen tas i bruk.

1. **September: 302,79 kr stemmer ikke med regnestykket.** 228,0 × 1,3280 = 302,784, som med vanlig avrunding gir 302,78. Perioden importeres med det faktisk fakturerte beløpet (302,79), og tallet regnes ikke om. Fremtidige oppgjør rundes halvt øre opp. Er det en annen avrundingsregel som er brukt (for eksempel alltid opp), må `beregn_belop` i `calc.py` endres.
2. **Kryssjekken mot `sensor.minusmaler_leilighet_import` er ikke bygget.** Den rå måleren er akkumulert fra 01.11.2026 og er bare lik utility_meter i første måned, så en enkel sammenligning ville gitt falske alarmer fra desember. Verdien eksponeres som attributt (`maaler_total_kwh`). Hva slags sjekk som ønskes, bør avklares.
3. **Ikke testet mot ekte Home Assistant eller ekte Gmail.** Sensorformene er lest fra den levende instansen, og alt annet er testet med mocket SMTP. Kjør `send_epost_pa_nytt` og test-e-posten i oppsettet, og åpne lenken fra mobil utenfor hjemmenettet (se «Overgang» under).
4. **Hvis du hopper over historikkimporten**, vil første kjøring prøve å lage oppgjør for forrige måned og sende det til leietaker.
5. **Ruter kan ikke fjernes i Home Assistant.** Etter `ny_leietaker` svarer den gamle lenken 404 umiddelbart, men ruten ligger registrert til neste omstart.
6. **App-passordet ligger i klartekst i config entry.**

## Overgang fra Claude-oppgavene

1. Installer og sett opp integrasjonen, importer historikken, send test-e-post.
2. Kjør `publiser_side` og sjekk lenken fra mobil utenfor hjemmenettet.
3. Kjør `generer_oppgjor` med `send_epost: false` for en testperiode og kontroller tallene.
4. Når november-oppgjøret (kjøres rundt 3. desember) går riktig fra Home Assistant, slås de to planlagte Claude-oppgavene av.

## Utvikling

```bash
pip install -r requirements_test.txt
ruff check . && pytest
```

Beregningen (`calc.py`), siden (`page.py`) og e-posten (`mail.py`) har ingen Home Assistant-avhengigheter og kan testes alene.
