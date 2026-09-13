"""
Logica di elaborazione per il fixer di Google Takeout Photos.

Scansiona una cartella di Takeout, associa ogni file media al proprio JSON di
metadati (con matching robusto/fallback), scrive i metadati nel file reale via
exiftool, aggiorna la mtime e copia il risultato in output/anno/mese.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov", ".gif"}
JSON_SUFFIXES = (".supplemental-metadata.json", ".json")

# Suffisso aggiunto da Google Foto alle copie modificate di una foto, nella
# lingua dell'account Google al momento dell'export. Un file "Nome-modificata.jpg"
# non ha un proprio JSON: il JSON esiste solo per l'originale "Nome.jpg".
EDITED_SUFFIXES = (
    "-edited",       # inglese
    "-modificata",   # italiano
    "-modifié",      # francese
    "-modifiziert",  # tedesco
    "-bearbeitet",   # tedesco (variante)
    "-editado",      # spagnolo/portoghese
    "-editada",      # spagnolo/portoghese (femminile)
    "-bewerkt",      # olandese
)


def _bundled_exiftool_path():
    """Percorso dell'exiftool "vendored" incluso nel bundle dell'app, se presente.

    Quando l'app è congelata con py2app, sys.frozen è vero e le risorse
    finiscono in Contents/Resources; in esecuzione da sorgente restano nella
    cartella vendor/ accanto a questo file.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent.parent / "Resources" / "vendor"
    else:
        base = Path(__file__).resolve().parent / "vendor"
    candidate = base / "exiftool" / "exiftool"
    return candidate if candidate.is_file() else None


def resolve_exiftool() -> str | None:
    bundled = _bundled_exiftool_path()
    if bundled is not None:
        return str(bundled)
    return shutil.which("exiftool")


def check_exiftool() -> bool:
    return resolve_exiftool() is not None


def strip_json_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in JSON_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


def find_json_for_media(media_path: Path, dir_json_cache: dict):
    media_name = media_path.name
    media_stem = media_path.stem
    media_suffix = media_path.suffix
    dir_path = media_path.parent

    candidates = [
        media_name + ".json",
        media_name + ".supplemental-metadata.json",
    ]

    # Google Takeout aggiunge un suffisso alle foto modificate nell'app Google
    # Foto, nella lingua dell'account: qui i casi noti. Il JSON associato resta
    # quello dell'originale (senza suffisso), non ne esiste uno per la versione
    # modificata.
    for suffix in EDITED_SUFFIXES:
        em = re.match(rf"^(.*){re.escape(suffix)}(\(\d+\))?$", media_stem, re.IGNORECASE)
        if em:
            original_stem = em.group(1) + (em.group(2) or "")
            original_name = original_stem + media_suffix
            candidates.append(original_name + ".json")
            candidates.append(original_name + ".supplemental-metadata.json")

    m = re.match(r"^(.*)(\(\d+\))(\.[^.]+)$", media_name)
    if m:
        base, num, ext = m.groups()
        candidates.append(f"{base}{ext}{num}.json")
        candidates.append(f"{base}{ext}{num}.supplemental-metadata.json")

    for candidate in candidates:
        p = dir_path / candidate
        if p.exists():
            return p

    if dir_path not in dir_json_cache:
        dir_json_cache[dir_path] = [
            p for p in dir_path.iterdir()
            if p.suffix.lower() == ".json" and not p.name.startswith("._")
        ]

    # Fallback per i nomi troncati dal vecchio limite di lunghezza di Google
    # Takeout: il nome del JSON è un PREFISSO troncato dell'intero nome del
    # media (es. media "AVeryLongName1234567890.jpg", json
    # "AVeryLongName1234.jpg.json"). Richiediamo che il nome del JSON sia
    # interamente contenuto come prefisso del nome del media, non solo che
    # condividano un tot di caratteri iniziali: due file con lo stesso
    # prefisso (stessa data, stesso "PXL_", numerazione sequenziale) ma
    # contenuto diverso dopo il prefisso NON sono un match, anche se
    # condividono molti caratteri iniziali.
    dir_jsons = dir_json_cache[dir_path]
    media_key = media_name.lower()
    best_match = None
    best_score = 0

    for jp in dir_jsons:
        base = strip_json_suffix(jp.name).lower()
        if len(base) < 8 or not media_key.startswith(base):
            continue
        score = len(base)
        if score > best_score:
            best_score = score
            best_match = jp

    if best_match is not None:
        dir_jsons.remove(best_match)
        return best_match

    return None


def parse_json_metadata(json_path: Path) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {
        "timestamp": None, "latitude": None, "longitude": None,
        "altitude": None, "description": None, "title": None,
    }

    photo_taken = data.get("photoTakenTime") or data.get("creationTime")
    if photo_taken and photo_taken.get("timestamp"):
        try:
            result["timestamp"] = int(photo_taken["timestamp"])
        except (TypeError, ValueError):
            pass

    geo = data.get("geoData") or data.get("geoDataExif")
    if geo:
        lat = geo.get("latitude")
        lng = geo.get("longitude")
        alt = geo.get("altitude")
        if lat not in (None, 0.0) or lng not in (None, 0.0):
            result["latitude"] = lat
            result["longitude"] = lng
            result["altitude"] = alt

    result["description"] = data.get("description") or None
    result["title"] = data.get("title") or None
    return result


def build_exiftool_args(meta: dict) -> list:
    args = []

    if meta["timestamp"] is not None:
        dt = datetime.fromtimestamp(meta["timestamp"], tz=timezone.utc)
        date_str = dt.strftime("%Y:%m:%d %H:%M:%S")
        args += [
            f"-AllDates={date_str}",
            f"-DateTimeOriginal={date_str}",
            f"-CreateDate={date_str}",
            f"-ModifyDate={date_str}",
            f"-TrackCreateDate={date_str}",
            f"-TrackModifyDate={date_str}",
            f"-MediaCreateDate={date_str}",
            f"-MediaModifyDate={date_str}",
        ]

    if meta["latitude"] is not None and meta["longitude"] is not None:
        lat, lng = meta["latitude"], meta["longitude"]
        lat_ref = "N" if lat >= 0 else "S"
        lng_ref = "E" if lng >= 0 else "W"
        args += [
            f"-GPSLatitude={abs(lat)}",
            f"-GPSLatitudeRef={lat_ref}",
            f"-GPSLongitude={abs(lng)}",
            f"-GPSLongitudeRef={lng_ref}",
        ]
        if meta["altitude"] is not None:
            alt = meta["altitude"]
            args += [
                f"-GPSAltitude={abs(alt)}",
                f"-GPSAltitudeRef={0 if alt >= 0 else 1}",
            ]

    text = meta["description"] or meta["title"]
    if text:
        safe_text = text.replace("\n", " ").strip()
        args += [
            f"-ImageDescription={safe_text}",
            f"-Description={safe_text}",
            f"-XMP:Description={safe_text}",
        ]
        if meta["title"]:
            args += [f"-Title={meta['title']}"]

    return args


def _run_exiftool_cmd(exiftool_bin: str, target: Path, exif_args: list):
    cmd = [
        exiftool_bin, "-m", "-overwrite_original",
        "-api", "QuickTimeUTC=1",
        "-api", "LargeFileSupport=1",
        *exif_args, str(target),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def run_exiftool(target: Path, exif_args: list):
    """Scrive i metadati con exiftool, con due tentativi di recupero mirati
    per i pattern di errore più comuni su export Google Takeout reali:

    1. Estensione non corrispondente al contenuto reale (es. un file
       ".HEIC" che in realtà è un JPEG): si rinomina temporaneamente il
       file con l'estensione corretta, si scrive, poi si ripristina il
       nome originale — l'utente vede comunque il nome esportato da Google.
    2. Struttura EXIF interna corrotta/troncata (es. "Can't read SubIFD
       data", "Error reading OtherImageStart data") che impedisce a
       exiftool di riscrivere il file preservando i tag esistenti: si
       elimina tutto l'EXIF esistente (già parzialmente illeggibile) e si
       riscrivono solo i tag che questo tool imposta. Distruttivo verso
       eventuali altri tag della fotocamera, quindi usato solo come
       ultima risorsa e sempre segnalato nel messaggio restituito.

    -m (-ignoreMinorErrors) è sempre passato: risolve da solo gli errori
    che exiftool stesso classifica come "[minor]" (es. puntatori IFD
    duplicati), senza alcun effetto collaterale.
    """
    if not exif_args:
        return True, ""
    exiftool_bin = resolve_exiftool()
    if exiftool_bin is None:
        return False, "exiftool non trovato"

    proc = _run_exiftool_cmd(exiftool_bin, target, exif_args)
    if proc.returncode == 0:
        return True, ""
    stderr = proc.stderr.strip()

    m = re.search(r"looks more like a (\w+)", stderr, re.IGNORECASE)
    if m:
        real_ext = "." + m.group(1).lower()
        temp_path = target.with_name(target.name + "__extfix" + real_ext)
        try:
            target.rename(temp_path)
            retry = _run_exiftool_cmd(exiftool_bin, temp_path, exif_args)
        finally:
            if temp_path.exists():
                temp_path.rename(target)
        if retry.returncode == 0:
            return True, f"[recuperato: estensione non corrispondeva al contenuto reale] {stderr}"
        stderr = retry.stderr.strip()

    strip_proc = subprocess.run(
        [exiftool_bin, "-m", "-all=", "-overwrite_original", str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if strip_proc.returncode == 0:
        retry2 = _run_exiftool_cmd(exiftool_bin, target, exif_args)
        if retry2.returncode == 0:
            return True, f"[recuperato eliminando l'EXIF preesistente, era illeggibile] {stderr}"

    return False, stderr


def output_path_for(base_output: Path, timestamp, filename: str) -> Path:
    if timestamp is not None:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        subdir = base_output / f"{dt.year:04d}" / f"{dt.month:02d}"
    else:
        subdir = base_output / "unknown_date"
    return subdir / filename


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def collect_media_files(input_root: Path) -> list:
    files = []
    for p in input_root.rglob("*"):
        # File "._Nome.jpg": sidecar AppleDouble che macOS crea per salvare
        # metadati Finder su filesystem che non li supportano (es. dischi
        # esterni exFAT/NTFS). Non sono foto reali: vanno ignorati, altrimenti
        # vengono scambiati per media e abbinati ad altrettanti JSON fantasma
        # (anch'essi file binari "._...json", non testo) causando eccezioni.
        if p.name.startswith("._"):
            continue
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS:
            files.append(p)
    return files


STRINGS = {
    "it": {
        "input_not_found": "Cartella di input non trovata: {path}",
        "scanning": "Scansione di {path} ...",
        "found_files": "Trovati {n} file media da elaborare.",
        "no_json": "[NO JSON] {name}",
        "exiftool_error": "[ERRORE exiftool] {name}: {err}",
        "exception": "[ECCEZIONE] {name}: {exc}",
        "done": "Elaborazione completata.",
        "error_log": "Log errori: {path}",
        "fatal_error": "[ERRORE FATALE] {exc}",
    },
    "en": {
        "input_not_found": "Input folder not found: {path}",
        "scanning": "Scanning {path} ...",
        "found_files": "Found {n} media files to process.",
        "no_json": "[NO JSON] {name}",
        "exiftool_error": "[exiftool ERROR] {name}: {err}",
        "exception": "[EXCEPTION] {name}: {exc}",
        "done": "Processing complete.",
        "error_log": "Error log: {path}",
        "fatal_error": "[FATAL ERROR] {exc}",
    },
}


class Job:
    """Rappresenta un'esecuzione del fixer, eseguita in un thread separato."""

    def __init__(self, input_dir: str, output_dir: str, dry_run: bool = False, jobs: int = 4, lang: str = "it"):
        self.input_root = Path(input_dir).expanduser().resolve()
        self.output_root = Path(output_dir).expanduser().resolve()
        self.dry_run = dry_run
        self.jobs = max(1, jobs)
        self.strings = STRINGS.get(lang, STRINGS["it"])

        self.state = "pending"  # pending -> scanning -> running -> done/error
        self.total = 0
        self.processed = 0
        self.missing_metadata = 0
        self.errors = 0
        self.log_lines = []
        self.error_message = None
        self._lock = threading.Lock()
        self._thread = None

    def t(self, key: str, **kwargs) -> str:
        return self.strings[key].format(**kwargs)

    def log(self, msg: str):
        with self._lock:
            self.log_lines.append(msg)
            if len(self.log_lines) > 2000:
                self.log_lines = self.log_lines[-2000:]

    def to_dict(self):
        with self._lock:
            return {
                "state": self.state,
                "total": self.total,
                "processed": self.processed,
                "missing_metadata": self.missing_metadata,
                "errors": self.errors,
                "error_message": self.error_message,
                "log_tail": self.log_lines[-200:],
            }

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            if not self.input_root.is_dir():
                raise RuntimeError(self.t("input_not_found", path=self.input_root))

            self.output_root.mkdir(parents=True, exist_ok=True)
            error_log_path = self.output_root / "errors.log"
            error_log_path.write_text("", encoding="utf-8")

            self.state = "scanning"
            self.log(self.t("scanning", path=self.input_root))
            media_files = collect_media_files(self.input_root)
            self.total = len(media_files)
            self.log(self.t("found_files", n=self.total))

            self.state = "running"
            dir_json_cache = {}
            cache_lock = threading.Lock()
            error_log_lock = threading.Lock()

            from concurrent.futures import ThreadPoolExecutor, as_completed

            def process_one(media_path: Path):
                try:
                    with cache_lock:
                        json_path = find_json_for_media(media_path, dir_json_cache)

                    meta = {
                        "timestamp": None, "latitude": None, "longitude": None,
                        "altitude": None, "description": None, "title": None,
                    }
                    has_metadata = False

                    if json_path is not None:
                        meta = parse_json_metadata(json_path)
                        has_metadata = True
                    else:
                        with self._lock:
                            self.missing_metadata += 1
                        with error_log_lock:
                            with open(error_log_path, "a", encoding="utf-8") as ef:
                                ef.write(f"NO_JSON\t{media_path}\n")
                        self.log(self.t("no_json", name=media_path.name))

                    dest_dir_time = meta["timestamp"]
                    if dest_dir_time is None:
                        dest_dir_time = int(media_path.stat().st_mtime)

                    dest_path = output_path_for(self.output_root, dest_dir_time, media_path.name)

                    if not self.dry_run:
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        dest_path = unique_path(dest_path)
                        shutil.copy2(media_path, dest_path)

                        if has_metadata:
                            exif_args = build_exiftool_args(meta)
                            ok, err = run_exiftool(dest_path, exif_args)
                            if not ok:
                                with self._lock:
                                    self.errors += 1
                                with error_log_lock:
                                    with open(error_log_path, "a", encoding="utf-8") as ef:
                                        ef.write(f"EXIFTOOL_ERROR\t{media_path}\t{err}\n")
                                self.log(self.t("exiftool_error", name=media_path.name, err=err))
                            elif err:
                                # scrittura riuscita solo grazie a un fallback di recupero:
                                # non è un errore, ma vale la pena tenerne traccia
                                with error_log_lock:
                                    with open(error_log_path, "a", encoding="utf-8") as ef:
                                        ef.write(f"EXIFTOOL_RECOVERED\t{media_path}\t{err}\n")

                            if meta["timestamp"] is not None:
                                ts = meta["timestamp"]
                                os.utime(dest_path, (ts, ts))

                    with self._lock:
                        self.processed += 1

                except Exception as exc:
                    with self._lock:
                        self.errors += 1
                    with error_log_lock:
                        with open(error_log_path, "a", encoding="utf-8") as ef:
                            ef.write(f"EXCEPTION\t{media_path}\t{exc}\n")
                    self.log(self.t("exception", name=media_path.name, exc=exc))

            with ThreadPoolExecutor(max_workers=self.jobs) as executor:
                futures = [executor.submit(process_one, mf) for mf in media_files]
                for _ in as_completed(futures):
                    pass

            self.log(self.t("done"))
            self.log(self.t("error_log", path=error_log_path))
            self.state = "done"

        except Exception as exc:
            self.error_message = str(exc)
            self.state = "error"
            self.log(self.t("fatal_error", exc=exc))
