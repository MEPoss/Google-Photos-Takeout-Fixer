<p align="center">
  <img src="docs/icon.png" width="128" alt="Icona Google Photos Takeout Fixer">
</p>

<h1 align="center">Google Photos Takeout Fixer</h1>

<p align="center">
  Ripristina data, GPS e descrizione nelle foto e nei video esportati da
  Google Foto con Google Takeout.
</p>

<p align="center">
  <img width="749" alt="Interfaccia" src="https://github.com/user-attachments/assets/0bd71405-7050-4edf-9a4b-0341d7733efe" />
</p>

## Il problema

Quando scarichi le tue foto da Google Foto tramite Google Takeout, l'export
è tecnicamente completo ma **inutilizzabile così com'è**:

- Ogni foto/video è accompagnato da un file `.json` separato con data, GPS e
  descrizione — ma questi dati **non sono scritti dentro il file media**
- Aprendo le foto in Anteprima, Finder, o importandole in una libreria foto,
  vedrai spesso la data di download invece della data reale dello scatto
- Riordinare per data o cercare per posizione diventa impossibile

## La soluzione

Google Photos Takeout Fixer legge ogni JSON e scrive i dati reali (data,
GPS, descrizione) **dentro** il file media stesso, usando `exiftool`:

- **Scrive i metadati EXIF** direttamente nei file media, calcolando anche
  il fuso orario reale dalle coordinate GPS invece di un finto UTC
- **Organizza i file** in output per anno/mese, senza mai toccare l'originale
- **Recupera automaticamente** i casi più comuni di scrittura fallita
  (estensione sbagliata, EXIF corrotto), segnalando sempre in chiaro cosa
  non è stato possibile sistemare, invece di far finta di niente

## Tutorial

### 1. Preparazione

Per usare Google Photos Takeout Fixer devi prima scaricare le tue foto da
Google Takeout ed estrarle:

1. Vai su [takeout.google.com](https://takeout.google.com/) e clicca
   "Deseleziona tutto"
2. Scorri e seleziona solo **Google Foto**
3. Scorri fino in fondo e clicca "Passaggio successivo"
4. Nella sezione "Trasferisci a", scegli come vuoi ricevere il link di
   download (email è il più semplice). Per "Dimensione file", scegli 50GB
   per una gestione più semplice
5. Clicca "Crea esportazione" e segui le istruzioni. Può richiedere ore o
   giorni per librerie grandi

> [!NOTE]
> Se il tuo export supera i 50GB, Google lo divide in più archivi separati
> (`Takeout`, `Takeout 2`, `Takeout 3`, ...). **Non serve unirli a mano**:
> estraili tutti dentro un'unica cartella (anche solo come sottocartelle
> una accanto all'altra) e punta Google Photos Takeout Fixer direttamente
> lì. Il programma cerca automaticamente i metadati anche tra le copie
> omonime di uno stesso album sparse tra i vari archivi, nel caso in cui
> Google abbia separato una foto dal proprio file JSON durante la
> divisione.

### 2. Installazione

1. Scarica l'ultima versione dalla [pagina delle release](../../releases) —
   scegli quella per il tuo sistema operativo (`.dmg` per macOS, `.deb` per
   Debian/derivate)
2. **macOS**: trascina l'app in Applications, poi aprila
3. **Debian/derivate**: installa con `sudo apt install ./nome-file.deb`

> [!IMPORTANT]
> Su macOS, al primo avvio potrebbe comparire un avviso di sicurezza perché
> l'app non è firmata/notarizzata (richiederebbe un account Apple Developer
> a pagamento). **Click destro sull'icona → Apri**, poi conferma — basta
> farlo una volta. Se non basta, vedi [Risoluzione problemi](#risoluzione-problemi-allavvio-macos)
> qui sotto.

### 3. Utilizzo di Google Photos Takeout Fixer

1. Clicca **"Scegli…"** e seleziona la cartella del Takeout estratto (input)
2. Clicca **"Scegli…"** e seleziona (o crea) una cartella vuota per l'output
3. Regola il numero di **worker paralleli** se necessario (di default 4 —
   valori più bassi sono più sicuri su dischi esterni meccanici)
4. Imposta un **fuso orario di riserva** se la maggior parte delle tue foto
   senza GPS proviene da un unico paese (default UTC)
5. Prova prima con **Dry run** attiva: simula l'intera elaborazione senza
   copiare o modificare nulla, mostrandoti in anteprima quanti file
   verrebbero processati, quanti senza JSON, quanti in errore
6. Se il risultato ti convince, disattiva Dry run e avvia l'elaborazione
   vera — l'originale non viene mai toccato, solo copiato

Una volta completata l'elaborazione, trovi i file sistemati nella cartella
di output che hai scelto, organizzati per anno/mese, con un riepilogo e un
link diretto alla sezione [FAQ](#faq-e-risoluzione-problemi) per interpretare
i numeri.

## Cosa fa, nel dettaglio

- Scansiona ricorsivamente una cartella Takeout estratta
- Associa ogni file media (`jpg`, `jpeg`, `png`, `heic`, `mp4`, `mov`, `gif`)
  al proprio JSON di metadati, con matching esatto e fallback sicuro su nomi
  troncati o pattern `(n)` spostati, riconoscendo anche le foto modificate
  nell'app Google Foto in più lingue (`-modificata`, `-edited`, ecc.)
- Scrive data scatto, coordinate GPS e descrizione nei metadati reali del
  file (EXIF per immagini, metadata contenitore per video) usando `exiftool`
- Calcola il fuso orario reale dalla posizione GPS (libreria offline, nessuna
  chiamata di rete), con un fuso di riserva selezionabile per i file senza GPS
- Recupera automaticamente i casi più comuni di scrittura fallita (estensione
  non corrispondente al contenuto reale, struttura EXIF corrotta), sempre
  annotando in chiaro quando lo fa
- Aggiorna la data di modifica del file sul filesystem
- Copia (non sposta) i file processati in `output/anno/mese`
- Logga in `errors.log` i file senza JSON associato, senza bloccarsi
- Mostra un riepilogo live nell'interfaccia (processati, mancanti, errori),
  in italiano o inglese in base alla lingua di sistema

## Requisiti

- macOS 11+ **oppure** Debian 12 (Bookworm) e derivate
- Se buildi da sorgente: Python 3.10+
- `exiftool`, incluso nella cartella `vendor/exiftool` (versione standalone
  Perl, nessuna dipendenza da Homebrew/apt); se assente, viene usato quello
  di sistema come fallback (`brew install exiftool` / `apt install
  libimage-exiftool-perl`)

## Risoluzione problemi all'avvio (macOS)

Se l'app non si apre nemmeno con click destro → Apri ("è danneggiata" o
non parte), rimuovi l'attributo di quarantena da terminale e riprova:

```bash
xattr -cr "/Applications/Google Photos Takeout Fixer.app"
open "/Applications/Google Photos Takeout Fixer.app"
```

Per vedere l'eventuale errore in chiaro, avvia il binario direttamente:

```bash
"/Applications/Google Photos Takeout Fixer.app/Contents/MacOS/Google Photos Takeout Fixer"
```

## Development

### Build da sorgente (macOS)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pywebview pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit py2app
.venv/bin/python3 setup.py py2app
```

L'app congelata finisce in `dist/Google Photos Takeout Fixer.app`, completa di
Python, dipendenze ed `exiftool` bundlati: non richiede nulla installato sul
Mac di destinazione.

### Build del pacchetto Debian

Il `.deb` viene costruito e testato automaticamente da
[`.github/workflows/build-deb.yml`](.github/workflows/build-deb.yml) dentro un
container `debian:bookworm` (crea il pacchetto, lo installa con `apt`, avvia
l'app sotto un display virtuale Xvfb e verifica che risponda davvero prima di
allegarlo alla release). Per riprodurlo in locale su una macchina Linux:

```bash
sudo packaging/debian/build.sh 1.0.0
```

### Struttura del progetto

- [`core.py`](core.py): logica di scansione, matching JSON, scrittura exif
- [`app.py`](app.py): server locale interno (usato solo dall'app, non pensato
  per essere aperto direttamente in un browser)
- [`launcher.py`](launcher.py): avvio come app nativa via `pywebview`
  (Cocoa su macOS, GTK/WebKit2 su Linux)
- [`templates/index.html`](templates/index.html): interfaccia (IT/EN)
- [`setup.py`](setup.py): build `.app` macOS con `py2app`
- [`packaging/debian`](packaging/debian): script e file per il pacchetto `.deb`
- [`vendor/exiftool`](vendor/exiftool): distribuzione standalone di ExifTool

## FAQ e risoluzione problemi

**Cosa significa "Senza JSON"?**
Sono file media per cui Google Takeout non ha esportato un file di metadati
JSON abbinato — capita per foto duplicate, generate dall'app Google Foto
(es. animazioni), o semplicemente per limiti dell'esportazione stessa. Non è
un bug: il file viene comunque copiato nella cartella di output, solo senza
data/GPS/descrizione aggiornati (mantiene la data di modifica del file
originale).

**Cosa significa "Errori"?**
Sono file per cui è successo qualcosa di anomalo durante la scrittura dei
metadati con `exiftool`. Il programma tenta automaticamente alcuni recuperi
prima di arrendersi:

- **Estensione non corrispondente al contenuto reale** (es. un file `.HEIC`
  che in realtà è un JPEG, comune negli export di Google Foto): il programma
  rinomina temporaneamente il file con l'estensione corretta, scrive i
  metadati, poi ripristina il nome originale. Nessuna azione richiesta.
- **Struttura EXIF interna corrotta o troncata** (es. `Can't read SubIFD
  data`, `Error reading OtherImageStart data`, spesso su foto passate per
  editor o riesportazioni): il programma elimina l'EXIF preesistente (già
  parzialmente illeggibile) e riscrive solo i tag che gestisce (data, GPS,
  descrizione). Questo viene comunque annotato in `errors.log` come
  `EXIFTOOL_RECOVERED`, così resta visibile che è successo, anche se non ha
  bloccato l'elaborazione.
- **Avvisi "minori" di exiftool** (es. puntatori IFD duplicati): risolti
  sempre in automatico, senza alcun effetto collaterale.

Se dopo tutto questo un file risulta ancora in errore, il dettaglio esatto è
scritto in `errors.log` nella cartella di output. Il caso più comune non
risolvibile è un file con estensione immagine ma contenuto in un formato che
`exiftool` non sa scrivere (es. un vero BMP salvato con estensione `.jpg`):
in quel caso il file viene comunque copiato correttamente, semplicemente non
sarà possibile aggiornarne i metadati interni.

**Un file scompare o non viene copiato?**
Non dovrebbe succedere: ogni file trovato nella cartella di input viene
sempre copiato in output, indipendentemente dal fatto che i suoi metadati
si riescano a scrivere o meno. Se un conteggio "Processati" risulta inferiore
al "Totale", significa che per quel file è stato sollevato un errore
imprevisto (categoria `EXCEPTION` in `errors.log`) prima ancora di
raggiungere la fase di copia — apri una
[issue](../../issues) allegando la riga corrispondente di `errors.log`.

**Perché il matching non è "indovina sempre qualcosa"?**
Perché è più sicuro dire onestamente "non trovato" che abbinare la foto
sbagliata. Il tool non tenta abbinamenti a bassa confidenza: se il nome del
JSON non è chiaramente riconducibile al file (match esatto, foto modificata,
o troncamento riconoscibile), il file viene copiato senza metadati invece di
rischiare di scrivere data/GPS di uno scatto diverso.

## Licenza

Google Photos Takeout Fixer è distribuito sotto licenza **MIT** — vedi
[LICENSE](LICENSE) per il testo completo. Puoi usarlo, modificarlo e
ridistribuirlo liberamente.

Le librerie usate possono avere licenze diverse. In particolare, questo
progetto include una copia di [ExifTool](https://exiftool.org/) di Phil
Harvey, distribuito sotto gli stessi termini di Perl (GPL o Artistic
License, a scelta) — vedi la relativa documentazione per i dettagli.

## Disclaimer

Progetto indipendente e gratuito, non affiliato con Google LLC. Fornito
"così com'è", senza garanzie di alcun tipo: usalo a tuo rischio, e mantieni
sempre una copia dell'export Takeout originale finché non sei soddisfatto
del risultato (questo tool non modifica mai l'originale, solo la copia in
output).
