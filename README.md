# Google Takeout Fixer

Ripristina i metadati (data, GPS, descrizione) nei file esportati con **Google
Takeout** da Google Foto. Google Takeout esporta ogni foto/video insieme a un
file JSON separato con i metadati originali — ma i file media spesso non li
hanno embeddati in EXIF. Questo strumento li scrive dove dovrebbero stare.

App desktop nativa per macOS con interfaccia web locale (Flask + finestra
nativa via `pywebview`), nessun terminale richiesto per l'uso quotidiano.

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

## Screenshot

Apri l'app, incolla (o seleziona da Finder) la cartella Takeout e quella di
output, avvia — progresso e log in tempo reale.

## Requisiti

- macOS 11+
- Se esegui da sorgente: Python 3.10+
- `exiftool` — incluso nella cartella `vendor/exiftool` (versione standalone
  Perl, nessuna dipendenza da Homebrew); se assente, viene usato quello di
  sistema come fallback (`brew install exiftool`)

## Uso — app pronta

Scarica l'ultima release (`.dmg`), trascina l'app in Applications, aprila.
Al primo avvio su un Mac diverso da quello di build, macOS potrebbe avvisare
che l'app è di uno sviluppatore non identificato (non è firmata/notarizzata):
click destro → **Apri** → conferma, una volta sola.

## Uso — da sorgente

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 app.py
```

Apri `http://127.0.0.1:5050` nel browser.

Per la versione con finestra nativa e selettore cartelle Finder:

```bash
.venv/bin/pip install pywebview pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit
.venv/bin/python3 launcher.py
```

## Build dell'app standalone (.app / .dmg)

```bash
.venv/bin/pip install py2app
.venv/bin/python3 setup.py py2app
```

L'app congelata finisce in `dist/Google Takeout Fixer.app`, completa di
Python, dipendenze ed `exiftool` bundlati — non richiede nulla installato sul
Mac di destinazione.

## Struttura del progetto

- [`core.py`](core.py) — logica di scansione, matching JSON, scrittura exif
- [`app.py`](app.py) — backend Flask (web UI + polling di stato)
- [`launcher.py`](launcher.py) — avvio come app nativa macOS via `pywebview`
- [`templates/index.html`](templates/index.html) — interfaccia
- [`setup.py`](setup.py) — build `.app` con `py2app`
- [`vendor/exiftool`](vendor/exiftool) — distribuzione standalone di ExifTool

## Licenza

MIT — vedi [LICENSE](LICENSE). Include ExifTool di Phil Harvey, distribuito
sotto i termini di Perl stesso (GPL/Artistic).
