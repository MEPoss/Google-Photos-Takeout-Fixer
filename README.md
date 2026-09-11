# Google Takeout Fixer

Ripristina i metadati (data, GPS, descrizione) nei file esportati con **Google
Takeout** da Google Foto. Google Takeout esporta ogni foto/video insieme a un
file JSON separato con i metadati originali, ma i file media spesso non li
hanno embeddati in EXIF. Questo strumento li scrive dove dovrebbero stare.

App desktop nativa per macOS, con finestra propria: nessun terminale e nessun
browser richiesti per l'uso quotidiano.

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

- macOS 11+
- Se buildi da sorgente: Python 3.10+
- `exiftool`, incluso nella cartella `vendor/exiftool` (versione standalone
  Perl, nessuna dipendenza da Homebrew); se assente, viene usato quello di
  sistema come fallback (`brew install exiftool`)

## Uso

Scarica il `.dmg` dalla sezione [Releases](../../releases), trascina l'app in
Applications, aprila. Al primo avvio su un Mac diverso da quello di build,
macOS potrebbe avvisare che l'app è di uno sviluppatore non identificato (non
è firmata/notarizzata): click destro sull'icona, poi **Apri**, poi conferma,
una volta sola.

## Build da sorgente

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pywebview pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit py2app
.venv/bin/python3 setup.py py2app
```

L'app congelata finisce in `dist/Google Takeout Fixer.app`, completa di
Python, dipendenze ed `exiftool` bundlati: non richiede nulla installato sul
Mac di destinazione.

## Struttura del progetto

- [`core.py`](core.py): logica di scansione, matching JSON, scrittura exif
- [`app.py`](app.py): server locale interno (usato solo dall'app, non pensato
  per essere aperto direttamente in un browser)
- [`launcher.py`](launcher.py): avvio come app nativa macOS via `pywebview`
- [`templates/index.html`](templates/index.html): interfaccia
- [`setup.py`](setup.py): build `.app` con `py2app`
- [`vendor/exiftool`](vendor/exiftool): distribuzione standalone di ExifTool

## Licenza

MIT, vedi [LICENSE](LICENSE). Include ExifTool di Phil Harvey, distribuito
sotto i termini di Perl stesso (GPL/Artistic).
