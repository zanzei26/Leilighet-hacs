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
| `sensor.minusmaler_leilighet_import` | Leilighetens målerstand i kWh (teller opp, nullstilles aldri). **Hovedkilden til forbruket.** |
| `sensor.minusmaler_leilighet_effekt` | Øyeblikkseffekt (W), kun til visning. |
| `sensor.mal_forbruk_prognose` | Attributtet `endring_prosent` brukes til månedsestimatet de tre første døgnene, eller når måleren ikke har gitt forbruk hittil. |
| `notify.notify` | Varslingstjeneste til utleier (en tjeneste, ikke en entitet). Dette er bare forslaget i skjemaet. Velg din egen. |

## Installasjon

1. HACS → ⋮ → **Egendefinerte repositories** → legg til `https://github.com/zanzei26/Leilighet-hacs` som kategori **Integration**.
2. Installer «Strømregnskap leietaker» og start Home Assistant på nytt.
3. **Innstillinger → Enheter og tjenester → Legg til integrasjon → Strømregnskap leietaker.**

## Oppsett (UI)

1. **Leietaker og utleier:** navn, e-post, adresse, innflyttingsdato, utleiers navn og e-post, kontonummer, forfallsdag (standard 15).
2. **Datakilder:** de fem sensorene og varslingstjenesten. Her kan du også slå på **elbil-laderen** (valgfritt, av som standard) og velge laderens teller. Se «Elbil-lader (valgfritt)».
3. **E-post (SMTP):** server (standard `smtp.gmail.com`), port (587), brukernavn, app-passord. Innloggingen testes før du kommer videre, og du kan la den sende en test-e-post til utleier. Kopi av hver e-post til utleier er på som standard, og det samme gjelder e-postkopien med PDF og sikkerhetskopi etter hvert oppgjør.
4. **Leietakerside:** på/av, og et valgfritt telefonnummer til utleier. Er nummeret fylt ut, står det en kontaktlinje nederst på siden («Spørsmål: <utleiers navn>, <telefon>») med en lenke leietaker kan trykke på for å ringe. Tomt felt gir ingen kontaktlinje. Nummeret lagres bare i oppsettet ditt i Home Assistant. Lenken vises i skjemaet.
5. **Rimelighetskontroll og kjøretid:** snittpris min 0,50 / maks 3,00 kr/kWh, maks ±60 % endring i kWh mot forrige periode, kjøring den 3. kl. 08:00 og sjekk til og med den 6.
6. **Eksisterende historikk:** importerer september (30.08–30.09) og oktober 2026 slik de er fakturert.

Alt kan endres senere under **Konfigurer** (menyvalg per tema). Passordfeltet kan stå tomt for å beholde gjeldende app-passord. App-passordet lagres i oppsettet uten kryptering (Home Assistant krypterer ikke config entries).

## Slik fungerer månedsoppgjøret

Koordinatoren kjører hver time. Fra kjøredagen kl. 08:00 til og med siste sjekkdag prøver den å lage oppgjør for forrige kalendermåned, hvis det ikke finnes fra før:

1. `sensor.jarvis_stromregnskap` må ha et element i `maneder` med riktig `mnd` og komplette tall for huset. Ellers prøves det igjen hver time. På siste sjekkdag, ved kjøretiden, får utleier ett varsel og en Repairs-melding. Har måneden **nøyaktig samme kWh og sum som måneden før**, regnes det som at kilden ikke har rullet over til den nye måneden ennå (for eksempel at Amperium ikke har oppdatert «forrige måned»). Da lages ingenting, det prøves igjen hver time, og feilmeldingen sier hvorfor. Ellers ville oppgjøret fått forrige måneds snittpris uten at noen kontroll slo ut. `tving` overstyrer det.
   **Sperre.** Kan regnskapssensoren ikke regne en måned riktig (for eksempel over 5 000 kWh, der Norgespris-modellen ikke gjelder), setter den feltet `sperre` på månedsraden med en forklaring. Da lages ikke oppgjøret, **heller ikke fra et øyeblikksbilde** (et bilde fra før grensen ble passert ser plausibelt ut, men er delvis og feil), og `tving` hjelper ikke. Utleier får «mangler data»-varselet med forklaringen. Mens inneværende måned er sperret, slettes månedens øyeblikksbilde, og det tidlige varselet om datagrunnlaget forklarer sperren. Legg fakturaens tall inn i regnskapssensoren (manuell overstyring), så lages oppgjøret ved neste timekjøring. En rad med `nettokraft_kilde: faktura` og komplette tall regnes som overstyrt og er ikke sperret, selv om forklaringen i `sperre` står igjen.
2. **Leilighetens kWh er målerstanden ved månedsskiftet minus målerstanden ved forrige månedsskifte**, slik man regnet før. Regnskapssensorens `leilighet_kwh` og utility_meterens `last_period` brukes som kontroll. Avviker noen av dem mer enn 0,5 kWh, eller mangler en av målerstandene, sendes ikke oppgjøret. Utleier får alle tallene og må godkjenne.
3. **Avrunding:** kWh og målerstander vises og regnes med én desimal (halvt opp). Beløp regnes fra det avrundede forbruket × snittprisen og avrundes til hele øre (halvt øre opp). Snittprisen beholder fire desimaler (kr/kWh), slik at regnestykket på fakturagrunnlaget går opp.
4. **Rimelighetskontroll** (snittpris innenfor grensene, 0 < leilighet ≤ hus, endring mot forrige periode innenfor grensen). Ved brudd får perioden status `venter_godkjenning`, utleier får varsel med tallene og hvilken regel som slo ut, og en Repairs-melding med «Godkjenn». Ingenting sendes, og perioden vises ikke på siden.
5. Ellers lagres perioden, siden oppdateres, og e-post sendes (kopi til utleier). Utleier får et kort push-varsel.
6. Feiler e-posten, beholdes perioden og det prøves igjen hver time i 48 timer. Utleier varsles én gang, og deretter kommer en Repairs-melding med «Send på nytt».

`ikke_betalt` blir automatisk `betalt` fra og med forfallsdagen. `unntak_ikke_betalt` forblir ubetalt til noen setter `betalt` (tillitsbasert, utleier sjekker nettbanken selv).

## Elbil-lader (valgfritt)

Har leietaker en egen elbil-lader som **ikke** går gjennom leilighetens måler, kan den tas med. Slå på «Ta med elbil-lader» under Datakilder og velg laderens **energiteller** (kWh, aldri nullstilt), for eksempel «Levetidsforbruk» fra Easee-integrasjonen. Er den av, er alt som før.

- **Samme metode som leilighetens måler.** Forbruket i en måned er telleren ved månedsskiftet minus telleren ved forrige månedsskifte (begge med én desimal). Telleren lagres rett etter midnatt, hentes ellers fra timesstatistikken, eller legges inn med `sett_malerstand` og `maaler: lader`. Laderens teller har ingen fornuftig startverdi å falle tilbake på. Finnes verken statistikk eller en avlesning, gjettes det ikke: perioden venter på godkjenning, og `binary_sensor.leietaker_datagrunnlag` sier fra.
- **Samme snittpris, egen linje.** Laderens kWh × husets snittpris regnes for seg og avrundes til hele øre. Beløpet leietaker skal betale er leilighetens beløp pluss laderens beløp (summen av de avrundede linjene, slik at fakturagrunnlaget går opp på papiret). Egne felt på perioden: `lader_kwh`, `lader_belop`, `leilighet_belop`, `lader_start`, `lader_slutt`. `leilighet_kwh` er fortsatt bare leiligheten.
- **Vises der leietaker ser det.** Egen linje i fakturagrunnlaget (tellerstander, forbruk, utregning), egne kolonner i hele regnskapet, linjer i e-posten, og i historikken på siden. Har laderen 0 kWh i en måned, skjules den på siden og i e-posten (fakturagrunnlaget viser 0,0 kWh).
- **Kontroller.** Teller som mangler eller går bakover (for eksempel ved lader-bytte), eller leilighet pluss lader over husets forbruk, gir `venter_godkjenning` med forklaring. Beløpet er da regnet uten lader, så du ser det før du godkjenner. Rett tellerne og lag perioden på nytt (slett, så generer). Endringsgrensen mot forrige måned gjelder bare leiligheten, siden lading kommer i rykk.
- **Live.** `forbruk_hittil` og `kostnad_hittil` er leilighet pluss lader. Delene ligger som attributter (`leilighet_kwh_hittil`, `lader_kwh_hittil`, `lader_kostnad_hittil`), og siden viser «Herav elbil-lader». Månedsestimatet bygger på leilighet pluss lader når det regnes fra takten. Regnes det fra forrige periode, er det bare leilighetens kWh.
- **Ikke med tilbakevirkende kraft.** Perioder som er laget før laderen ble slått på, endres ikke.

## Datasikkerhet

Målet er at et hull i én kilde aldri gjør at du står uten grunnlag ved månedsskiftet.

- **Målerstander.** (Gjelder også laderens teller når den er på, i en egen serie `laderstander`.) Integrasjonen lagrer målerstanden rett etter midnatt ved hvert månedsskifte. Mangler en avlesning (for eksempel fordi Home Assistant var nede), hentes den fra Home Assistants timesstatistikk, eller du legger den inn med handlingen `sett_malerstand`. En lagret avlesning overskrives aldri automatisk. Ved første oppsett lagres startstanden du oppgir, eller statistikken hvis den finnes.
- **Fast lagring som overlever.** Historikken ligger under en fast nøkkel i `.storage`, uavhengig av config entry. Fjerner du integrasjonen og legger den til igjen, er historikken der fortsatt. Data fra 0.1.x flyttes automatisk.
- **Rullerende sikkerhetskopier.** Hver endring gir en JSON-kopi i `/config/stromregnskap_leietaker/sikkerhetskopi/` (de 20 nyeste, pluss den nyeste fra hver eldre måned). Kopiene dekkes av vanlige Home Assistant-sikkerhetskopier. Er lagringsfilen borte eller ødelagt, gjenopprettes siste gyldige kopi automatisk i stedet for at integrasjonen starter tom. Feil ved sikkerhetskopiering stopper aldri selve lagringen, men vises i `binary_sensor.leietaker_datagrunnlag`.
- **Øyeblikksbilde av kildetallene.** Hver sjette time lagres husets tall for måneden som pågår. Mister regnskapssensoren en måned før oppgjøret lages, brukes siste bilde som reserve. Den automatiske kjøringen venter med reserven til varseltidspunktet på siste sjekkdag, slik at regnskapssensoren får hele vinduet til å rette seg (prøver hver time, og et vanlig oppgjør lages så snart tallene er der). **Et oppgjør bygd på et øyeblikksbilde sendes aldri automatisk**, det venter alltid på din godkjenning.
- **Tidlig varsel.** `binary_sensor.leietaker_datagrunnlag` er `on` hvis noe hindrer at neste oppgjør kan lages trygt (utilgjengelig regnskapssensor eller måler, manglende målerstand, gammelt øyeblikksbilde, feilende sikkerhetskopi). Fra den 25. får du dessuten ett varsel per dag og en melding under Reparasjoner, slik at du vet det dager før månedsskiftet.
- **Etterslep.** Er oppgjøret for forrige måned ikke laget når den automatiske kjøringen er over (for eksempel fordi Home Assistant var nede 3.–6.), får du daglig varsel og en reparasjon som lager det.

Gjenoppretting skjer automatisk bare når lagringen mangler eller er ødelagt. Det finnes ingen handling for å gå tilbake til en bestemt kopi. Vil du det, kan du stoppe Home Assistant, erstatte feltet `data` i `.storage/stromregnskap_leietaker` med feltet `data` fra den kopien du vil tilbake til, og starte igjen. Filene har samme form, og du bør ta en ekstra kopi av begge først.

## Fakturagrunnlag og regnskap (PDF)

Alt er ferdig utregnet, med utregningen synlig, slik at både du og leietaker kan kontrollere tallene uten å regne selv.

- **Fakturagrunnlag per måned** (én side): parter, periode, målerstand ved start og slutt, ditt forbruk, husets kostnader (kraft, nettleie, Norgespris, sum, husets forbruk og snittpris), utregningen `kWh × snittpris = beløp`, betalingsinformasjon og status.
- **Hele regnskapet fra start**: sammendrag (totalt fakturert, betalt, utestående), alle oppgjør, og husets kostnader per måned. Lange regnskap fortsetter på flere sider med overskriften gjentatt.
- **Leietaker** har knapper på siden sin: «Last ned PDF» under hver måned, og «Last ned hele regnskapet (PDF)». PDF-ene bygges ferskt ved hver nedlasting, krever ingen innlogging (som siden, bak den hemmelige lenken), og oppgjør som venter på godkjenning er ikke med.
- **Leietaker** får regningen for perioden **vedlagt som PDF** i oppgjørs-e-posten. Skulle PDF-en ikke kunne lages, sendes oppgjøret likevel uten vedlegg (teksten lover da ikke noe vedlegg), og du får et varsel.
- Med handlingen `send_faktura` kan du sende leietaker lenken til siden og regningen for en bestemt periode (standard: siste oppgjør) som PDF-vedlegg, for eksempel for å sende en regning på nytt med fersk lenke etter at leietakers e-postadresse er byttet. E-posten forteller også at hele regnskapet ligger på siden og at forbruket for inneværende måned er live.
- **Utleier** får en **kopi på e-post** etter hvert oppgjør (kan slås av under Konfigurer → E-post). Emnet er «Fakturagrunnlag strøm leilighet – <måned år>». Vedlagt er fakturagrunnlaget, hele regnskapet og en **JSON-sikkerhetskopi** av alle data. Det er en kopi utenfor Home Assistant som ikke forsvinner. Du kan også trykke «Send regnskap» (eller bruke handlingen `send_regnskap`) når som helst.
- Lenkene til PDF-ene står som attributter på `sensor.leietaker_lenke`.

PDF-ene lages av en egen liten skriver uten eksterne biblioteker, så det er ingenting ekstra som må installeres.

## Leietakersiden

Integrasjonen skriver én selvstendig HTML-fil (ingen JavaScript, ingen eksterne ressurser, `noindex`, lys/mørk modus) til `/config/www/<hemmelig-slug>/index.html` hver time og ved alle endringer. Lenken er `https://<nabu-casa-id>.ui.nabu.casa/local/<slug>/index.html` (Nabu Casa først, ellers ekstern/intern URL).

**Live-tall.** «Forbruk hittil» regnes på samme måte som oppgjøret: målerstand nå minus målerstand ved månedsskiftet (begge med én desimal). Sensorene `forbruk_hittil` og `kostnad_hittil` oppdateres derfor med en gang minusmåleren endrer seg, uten å vente på den timelige kjøringen. Raske endringer slås sammen til høyst én oppdatering per 15 sekunder, og den timelige kjøringen går som før. Attributtet `kilde_hittil` viser om tallet kommer fra måleren (`maaler`) eller fra reserven (`utility_meter`, når målerstanden ved månedsskiftet mangler). Leietakersiden bygges på nytt for hver innlasting og laster seg selv på nytt hvert minutt. Er regnskapssensoren utilgjengelig, vises forbruket fra måleren uten kostnad. Prisen gjettes aldri.

Siden leveres av en egen rute på nøyaktig denne URL-en, og ikke av Home Assistants vanlige `/local`. Årsaken er at `/local` bare finnes hvis `www`-mappen fantes ved oppstart, og at den leverer filer med `Cache-Control: public, max-age=2678400` (31 dager), slik at leietakers nettleser kunne vist gamle tall i en måned. Ruten svarer uten innlogging med `Cache-Control: no-store`.

## Entiteter

Alle entitetene ligger på én enhet, «Leietaker».

| Entitet | Innhold |
|---|---|
| `sensor.leietaker_utestaende` | Sum ubetalt (kr). Attributter: antall perioder, lenke. |
| `sensor.leietaker_siste_oppgjor` | Beløp siste periode (kr). Attributter: alle feltene i perioden. |
| `sensor.leietaker_forbruk_hittil` | kWh denne måneden. Attributter: snittpris og kostnad hittil, estimat og `estimat_metode`, `endring_prosent`, effekt (W), rå målerstand. |
| `sensor.leietaker_kostnad_hittil` | Kostnad hittil (kr). |
| `sensor.leietaker_estimat_maned` | Månedsestimat (kr). Attributter: kWh og `estimat_metode` (`takt`, `forrige_periode` eller `ingen`). |
| `sensor.leietaker_side_sist_publisert` | Tidsstempel. Attributt: lenke. |
| `sensor.leietaker_lenke` | Leietakerlenken, slik at du kan se og kopiere den. Ukjent hvis siden ikke publiseres. Attributter: lenker til regnskapet og siste fakturagrunnlag (PDF). |
| `binary_sensor.leietaker_oppgjor_venter_godkjenning` | `on` når en periode venter på godkjenning. |
| `binary_sensor.leietaker_datagrunnlag` | `on` (problem) hvis noe hindrer at neste oppgjør kan lages trygt. Attributter: problemene, siste målerstander, siste øyeblikksbilde og sikkerhetskopi. |
| `button.leietaker_send_lenke` | Sender en kort e-post til leietaker med bare lenken. |
| `button.leietaker_merk_som_betalt` | Merker alle utestående oppgjør som betalt. |
| `button.leietaker_send_regnskap` | Sender deg en e-post med fakturagrunnlag, regnskap (PDF) og JSON-sikkerhetskopi. |

Estimatet bygger fra og med 72 timer (3 døgn) ut i måneden på leilighetens egen takt: forbruk hittil fra måleren ÷ medgått tid × månedens lengde, regnet i timer fra lokal midnatt den 1. (klokkeskifte og 28–31 dager blir riktig). De tre første døgnene, og når målerstanden ved månedsskiftet mangler, er det forrige periodes leilighets-kWh × (1 + `endring_prosent`/100). Prisen er i begge tilfeller forrige periodes snittpris. Uten forrige periode vises ikke noe estimat. Metoden står i attributtet `estimat_metode` på `forbruk_hittil` og `estimat_maned`. «Hittil»-tall fra regnskapssensoren brukes bare når den faktisk viser inneværende måned.

> **Installerte du 0.1.0?** Da kan entity-ID-ene dine ha fått «leietaker» to ganger (for eksempel `sensor.stromregnskap_leietaker_leietaker_utestaende`). Det er rettet i 0.1.1, men eksisterende entiteter beholder navnet sitt. Fjern integrasjonen og legg den til på nytt, eller gi entitetene nytt navn i Home Assistant.

## Tjenester

| Tjeneste | Felt | Gjør |
|---|---|---|
| `stromregnskap_leietaker.generer_oppgjor` | `periode` (ÅÅÅÅ-MM, standard forrige måned), `tving`, `send_epost` | Lager oppgjør manuelt. `tving` hopper over rimelighetskontrollen. |
| `stromregnskap_leietaker.godkjenn_oppgjor` | `periode` | Sender et oppgjør som venter på godkjenning. |
| `stromregnskap_leietaker.send_epost_pa_nytt` | `periode` | Sender oppgjøret på e-post på nytt. |
| `stromregnskap_leietaker.send_lenke` | | Sender en kort e-post til leietaker med lenken til siden. |
| `stromregnskap_leietaker.send_faktura` | `periode` (valgfri) | Sender leietaker lenken til siden og regningen for perioden (siste oppgjør hvis ingen er valgt) som PDF-vedlegg. Endrer ikke perioden. |
| `stromregnskap_leietaker.send_regnskap` | `periode` (valgfri) | Sender deg en e-post med fakturagrunnlag (siste periode hvis ingen er valgt), hele regnskapet og JSON-sikkerhetskopi. |
| `stromregnskap_leietaker.merk_betalt` | `periode` (valgfri) | Merker utestående oppgjør som betalt. Uten periode: alle utestående. |
| `stromregnskap_leietaker.sett_malerstand` | `dato` (første dag i måneden), `stand` (kWh), `maaler` (`leilighet`, standard, eller `lader`) | Legger inn eller retter målerstanden ved et månedsskifte. |
| `stromregnskap_leietaker.sett_status` | `periode`, `status` | `betalt`, `ikke_betalt` eller `unntak_ikke_betalt`. |
| `stromregnskap_leietaker.publiser_side` | | Lager siden på nytt nå. |
| `stromregnskap_leietaker.slett_periode` | `periode`, `bekreft: true` | Sletter en periode. Et sendt oppgjør er låst og kan bare fjernes slik. |
| `stromregnskap_leietaker.ny_leietaker` | | Leietakerskifte, se under. |

## Leietakerskifte

`ny_leietaker` arkiverer all historikk til `/config/stromregnskap_leietaker/arkiv/<navn>_<dato>.json`, tømmer historikken, bytter slug (ny lenke, og den gamle slutter å virke) og åpner rekonfigurering for de nye leietakeropplysningene. Rekonfigureringen åpnes fra ⋮-menyen på integrasjonen. Tjenesten starter også selve flyten og returnerer arkivfilen og den nye lenken.

## Datamodell

Lagres med Home Assistants `Store` (`stromregnskap_leietaker.<entry_id>`, versjonert med migrering). Hver periode har `id`, `start`, `slutt`, `leilighet_kwh`, `hus_kwh`, `kraft`, `nettleie`, `norgespris`, `sum`, `snitt`, `belop`, `forfall`, `status`, `generert`, `epost_sendt`, `kilde` og `notat`. Med elbil-lader på kommer i tillegg `leilighet_belop`, `lader_kwh`, `lader_belop`, `lader_start` og `lader_slutt`, og `belop` er da totalen.

Tillegg utover den opprinnelige skissen:

- `epost_ventende_siden`: når utsendingsforsøkene startet (`null` når ingenting venter). Trengs for 48-timersgrensen, siden et godkjent oppgjør kan være dager gammelt.
- `tilstand.varslet`: nøkler for varsler som allerede er sendt, så de ikke gjentas hver time.
- `tilstand.historikk_importert`: hindrer at historikken importeres to ganger.

## Åpne punkter

Dette er avvik og ting som ikke er gjort. Det er viktig å se på dem før integrasjonen tas i bruk.

1. **September: 302,79 kr (avklart).** 228,0 × 1,3280 = 302,784, så det oppgitte beløpet stemmer ikke helt med regnestykket. Vanlig avrunding gjelder (halvt øre opp). Perioden importeres med det faktisk fakturerte beløpet, 302,79 kr, og regnes ikke om.
2. **Kryssjekken er nå bygget** (se «Datasikkerhet»): målerstandene regnes mot regnskapssensoren og utility_meter, og avvik over 0,5 kWh krever godkjenning.
3. **Ikke testet mot ekte Home Assistant eller ekte Gmail.** Sensorformene er lest fra den levende instansen, og alt annet er testet med mocket SMTP. Kjør `send_epost_pa_nytt` og test-e-posten i oppsettet, og åpne lenken fra mobil utenfor hjemmenettet (se «Overgang» under).
4. **Hvis du hopper over historikkimporten**, vil første kjøring prøve å lage oppgjør for forrige måned og sende det til leietaker.
5. **Ruter kan ikke fjernes i Home Assistant.** Etter `ny_leietaker` svarer den gamle lenken 404 umiddelbart, men ruten ligger registrert til neste omstart.
6. **App-passordet ligger i klartekst i config entry.**
7. **Uthenting av målerstand fra statistikken er best effort og ikke verifisert mot en ekte Home Assistant.** Den brukes bare som reserve hvis integrasjonen ikke var oppe ved midnatt. Virker den ikke, får du «målerstand mangler» i `binary_sensor.leietaker_datagrunnlag`, og du legger inn tallet med `sett_malerstand`.
8. **Etter oppdatering til 0.2.0:** sjekk under Konfigurer → Datakilder at «Målerstand ved start av denne måneden» er riktig (0 hvis måleren startet på 0), og at `binary_sensor.leietaker_datagrunnlag` er `off`.
9. **Kopien utenfor Home Assistant avhenger av e-post.** Den kommer bare hvis e-posten til leietaker først gikk gjennom, og feiler kopien, får du et varsel (oppgjøret stoppes ikke). Sjekk at e-postene kommer frem de første månedene.
10. **PDF-ene er ikke åpnet i alle lesere.** Layout er kontrollert visuelt og teksten er verifisert med en uavhengig leser (pypdf), men de er ikke prøvd i for eksempel en mobil-PDF-leser.

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
