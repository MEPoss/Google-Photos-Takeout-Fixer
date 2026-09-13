<p align="center">
  <img src="docs/icon.png" width="128" alt="Icona Google Photos Takeout Fixer">
</p>

# Google Photos Takeout Fixer

Ripristina i metadati (data, GPS, descrizione) nei file esportati con **Google
Takeout** da Google Foto. Google Takeout esporta ogni foto/video insieme a un
file JSON separato con i metadati originali, ma i file media spesso non li
hanno embeddati in EXIF. Questo strumento li scrive dove dovrebbero stare.

App desktop nativa per macOS, con finestra propria: nessun terminale e nessun
browser richiesti per l'uso quotidiano.

<p align="center">
  <img width="749" height="477" alt="image" src="https://github.com/user-attachments/assets/0bd71405-7050-4edf-9a4b-0341d7733efe" />
</p>

## Cosa fa

- Scansiona ricorsivamente una cartella Takeout estratta
- Associa ogni file media (`jpg`, `jpeg`, `png`, `heic`, `mp4`, `mov`, `gif`)
  al proprio JSON di metadati, con matching robusto e fallback su nomi
  troncati o pattern `(n)` spostati
- Scrive data scatto, coordinate GPS e descrizione nei metadati reali del
  file (EXIF per immagini, metadata contenitore per video) usando `exiftool`
- Aggiorna la data di modifica del file sul filesystem
- Copia (non sposta) i file processati in `output/anno/mese`
- Logga in `errors.log` i file senza JSON associato, senza bloccarsi
- Mostra un riepilogo live nell'interfaccia (processati, mancanti, errori)

## Requisiti

- macOS 11+ **oppure** Debian 12 (Bookworm) e derivate
- Se buildi da sorgente: Python 3.10+
- `exiftool`, incluso nella cartella `vendor/exiftool` (versione standalone
  Perl, nessuna dipendenza da Homebrew/apt); se assente, viene usato quello
  di sistema come fallback (`brew install exiftool` / `apt install
  libimage-exiftool-perl`)

## Uso (macOS)

Scarica il `.dmg` dalla sezione [Releases](../../releases), trascina l'app in
Applications, aprila. Al primo avvio macOS potrebbe avvisare che l'app è di
uno sviluppatore non identificato (non è firmata né notarizzata: richiederebbe
un account Apple Developer a pagamento): click destro sull'icona, poi **Apri**,
poi conferma, una volta sola.

Se anche così non si apre ("è danneggiata" o l'app non parte), rimuovi
l'attributo di quarantena da terminale e riprova:

```bash
xattr -cr "/Applications/Google Photos Takeout Fixer.app"
open "/Applications/Google Photos Takeout Fixer.app"
```

Per vedere l'eventuale errore in chiaro, avvia il binario direttamente:

```bash
"/Applications/Google Photos Takeout Fixer.app/Contents/MacOS/Google Photos Takeout Fixer"
```

## Uso (Debian / derivate)

Scarica il pacchetto `.deb` dalla sezione [Releases](../../releases) e
installalo:

```bash
sudo apt install ./google-photos-takeout-fixer_<versione>_all.deb
```

`apt` risolve da solo le dipendenze (Python 3, GTK, WebKit2GTK, Perl). L'app
compare nel menu applicazioni, oppure si avvia da terminale con:

```bash
google-photos-takeout-fixer
```

## Build da sorgente (macOS)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pywebview pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit py2app
.venv/bin/python3 setup.py py2app
```

L'app congelata finisce in `dist/Google Photos Takeout Fixer.app`, completa di
Python, dipendenze ed `exiftool` bundlati: non richiede nulla installato sul
Mac di destinazione.

## Build del pacchetto Debian

Il `.deb` viene costruito e testato automaticamente da
[`.github/workflows/build-deb.yml`](.github/workflows/build-deb.yml) dentro un
container `debian:bookworm` (crea il pacchetto, lo installa con `apt`, avvia
l'app sotto un display virtuale Xvfb e verifica che risponda davvero prima di
allegarlo alla release). Per riprodurlo in locale su una macchina Linux:

```bash
sudo packaging/debian/build.sh 1.0.0
```

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

## Struttura del progetto

- [`core.py`](core.py): logica di scansione, matching JSON, scrittura exif
- [`app.py`](app.py): server locale interno (usato solo dall'app, non pensato
  per essere aperto direttamente in un browser)
- [`launcher.py`](launcher.py): avvio come app nativa via `pywebview`
  (Cocoa su macOS, GTK/WebKit2 su Linux)
- [`templates/index.html`](templates/index.html): interfaccia (IT/EN)
- [`setup.py`](setup.py): build `.app` macOS con `py2app`
- [`packaging/debian`](packaging/debian): script e file per il pacchetto `.deb`
- [`vendor/exiftool`](vendor/exiftool): distribuzione standalone di ExifTool

## Licenza

MIT, vedi [LICENSE](LICENSE). Include ExifTool di Phil Harvey, distribuito
sotto i termini di Perl stesso (GPL/Artistic).
