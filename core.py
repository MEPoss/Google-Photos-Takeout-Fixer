"""
Logica di elaborazione per il fixer di Google Takeout Photos.

Scansiona una cartella di Takeout, associa ogni file media al proprio JSON di
metadati (con matching robusto/fallback), scrive i metadati nel file reale via
exiftool, aggiorna la mtime e copia il risultato in output/anno/mese.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_TZFINDER = None


def _get_timezone_finder():
    """Istanzia TimezoneFinder pigramente: il caricamento dei dati geografici
    costa qualche decina di ms, non ha senso pagarlo se non serve mai."""
    global _TZFINDER
    if _TZFINDER is None:
        from timezonefinder import TimezoneFinder

        _TZFINDER = TimezoneFinder()
    return _TZFINDER


def resolve_timezone(lat, lng, fallback_tz: str = "UTC") -> ZoneInfo:
    """Determina il fuso orario reale dalle coordinate GPS della foto. Se le
    coordinate mancano o non ricadono in nessun fuso noto, usa il fuso di
    riserva impostato dall'utente (default UTC)."""
    if lat is not None and lng is not None:
        try:
            tf = _get_timezone_finder()
            tz_name = tf.timezone_at(lat=lat, lng=lng)
            if tz_name:
                return ZoneInfo(tz_name)
        except Exception:
            pass
    try:
        return ZoneInfo(fallback_tz)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")

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


MOTION_PHOTO_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".heic", ".png")
MOTION_PHOTO_VIDEO_EXTENSIONS = (".mp4", ".mov")


def _json_candidates_for_name(name: str) -> list:
    """Genera i possibili nomi di JSON per un nome di file media (con estensione).

    Gestisce anche il caso dei file duplicati nella stessa cartella (stesso
    nome caricato due volte): Google Takeout rinomina il media in
    "base(1).ext", "base(2).ext", ecc., ma il JSON del duplicato non prende
    il "(n)" subito dopo il nome come ci si aspetterebbe, bensì alla fine,
    dopo il suffisso "supplemental-metadata" (es. media "salone(1).jpg" ->
    json "salone.jpg.supplemental-metadata(1).json"). Va applicata anche al
    nome "originale" ricostruito da una foto "-modificata(1)", perché quel
    duplicato ha comunque un proprio JSON con lo stesso schema.
    """
    candidates = [name + ".json", name + ".supplemental-metadata.json"]
    m = re.match(r"^(.*)(\(\d+\))(\.[^.]+)$", name)
    if m:
        base, num, ext = m.groups()
        candidates.append(f"{base}{ext}.supplemental-metadata{num}.json")
        candidates.append(f"{base}{ext}{num}.json")
        candidates.append(f"{base}{ext}{num}.supplemental-metadata.json")
        # Per foto senza un nome "da fotocamera" (importate, incollate, o
        # rinominate nell'interfaccia di Google Foto: es. "Parco Nord.jpg")
        # il JSON a volte perde del tutto l'estensione originale, pur
        # mantenendo il contatore del duplicato: "Parco Nord(1).jpg" ->
        # "Parco Nord.supplemental-metadata(1).json" (non "Parco
        # Nord.jpg.supplemental-metadata(1).json").
        candidates.append(f"{base}.supplemental-metadata{num}.json")
    else:
        base, ext = os.path.splitext(name)
        if ext:
            # Stesso fenomeno del caso sopra, ma senza contatore duplicato:
            # "download.jpg" -> "download.supplemental-metadata.json".
            candidates.append(f"{base}.supplemental-metadata.json")
    return candidates


def find_json_for_media(media_path: Path, dir_json_cache: dict, dir_sibling_cache: dict | None = None,
                         dir_name_index: dict | None = None):
    media_name = media_path.name
    media_stem = media_path.stem
    media_suffix = media_path.suffix
    dir_path = media_path.parent

    candidates = _json_candidates_for_name(media_name)

    # Google Takeout aggiunge un suffisso alle foto modificate nell'app Google
    # Foto, nella lingua dell'account: qui i casi noti. Il JSON associato resta
    # quello dell'originale (senza suffisso), non ne esiste uno per la versione
    # modificata.
    for suffix in EDITED_SUFFIXES:
        em = re.match(rf"^(.*){re.escape(suffix)}(\(\d+\))?$", media_stem, re.IGNORECASE)
        if em:
            original_stem = em.group(1) + (em.group(2) or "")
            original_name = original_stem + media_suffix
            candidates += _json_candidates_for_name(original_name)

    # Un export grande viene diviso da Google in più cartelle "Takeout N"
    # separate, ognuna con la propria copia di un identico nome di album
    # (es. "Foto da 2018" in Takeout, Takeout 2, Takeout 3...): le foto di
    # un album finiscono sparse tra queste copie, e il JSON di una foto può
    # trovarsi in una copia diversa da quella della foto stessa. Se il JSON
    # non è nella cartella del file, lo cerchiamo quindi (con lo stesso
    # matching esatto, non fuzzy) anche in tutte le altre cartelle
    # dell'export che hanno lo stesso nome della cartella madre diretta.
    search_dirs = [dir_path]
    if dir_name_index is not None:
        for other_dir in dir_name_index.get(dir_path.name, ()):
            if other_dir != dir_path:
                search_dirs.append(other_dir)

    for search_dir in search_dirs:
        for candidate in candidates:
            p = search_dir / candidate
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

    # "Motion Photo" di Google Pixel (e Live Photo simili): un video
    # "MVIMG_xxx.mp4" affiancato da una foto sorella "MVIMG_xxx.jpg" (stesso
    # nome, estensione diversa) non ha un proprio JSON: i metadati (data,
    # GPS) sono solo su quello della foto, che va riusato anche per il
    # video. La foto sorella può trovarsi in una qualunque delle cartelle
    # omonime (search_dirs) così come il video, ma il suo JSON può essere
    # finito in una cartella omonima ANCORA DIVERSA da quella della foto
    # stessa (stesso motivo per cui un video può essere separato dal proprio
    # JSON): la ricerca del JSON va quindi ripetuta su tutte le search_dirs,
    # non solo su quella in cui si è trovata la foto sorella. Non tocca
    # dir_json_cache: la foto sorella userà comunque lo stesso JSON tramite
    # il match esatto quando verrà elaborata a sua volta.
    if dir_sibling_cache is not None and media_suffix.lower() in MOTION_PHOTO_VIDEO_EXTENSIONS:
        sibling_photo = None
        for search_dir in search_dirs:
            if search_dir not in dir_sibling_cache:
                dir_sibling_cache[search_dir] = [
                    p for p in search_dir.iterdir()
                    if p.is_file() and p.suffix.lower() != ".json" and not p.name.startswith("._")
                ]
            for sibling in dir_sibling_cache[search_dir]:
                if sibling.suffix.lower() in MOTION_PHOTO_IMAGE_EXTENSIONS and sibling.stem.lower() == media_stem.lower():
                    sibling_photo = sibling
                    break
            if sibling_photo is not None:
                break

        if sibling_photo is not None:
            for search_dir in search_dirs:
                for json_suffix in JSON_SUFFIXES:
                    jp = search_dir / (sibling_photo.name + json_suffix)
                    if jp.exists():
                        return jp

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


def build_exiftool_args(meta: dict, fallback_tz: str = "UTC") -> list:
    args = []

    if meta["timestamp"] is not None:
        utc_dt = datetime.fromtimestamp(meta["timestamp"], tz=timezone.utc)
        tz = resolve_timezone(meta["latitude"], meta["longitude"], fallback_tz)
        local_dt = utc_dt.astimezone(tz)
        date_str = local_dt.strftime("%Y:%m:%d %H:%M:%S")
        offset_str = local_dt.strftime("%z")  # es. "+0200"
        offset_str = f"{offset_str[:3]}:{offset_str[3:]}"  # exiftool vuole "+02:00"
        args += [
            f"-AllDates={date_str}",
            f"-DateTimeOriginal={date_str}",
            f"-CreateDate={date_str}",
            f"-ModifyDate={date_str}",
            f"-TrackCreateDate={date_str}",
            f"-TrackModifyDate={date_str}",
            f"-MediaCreateDate={date_str}",
            f"-MediaModifyDate={date_str}",
            f"-OffsetTime={offset_str}",
            f"-OffsetTimeOriginal={offset_str}",
            f"-OffsetTimeDigitized={offset_str}",
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


def build_dir_name_index(input_root: Path, should_stop=None) -> dict:
    """Indicizza tutte le sottocartelle di input_root per nome, in modo da
    poter cercare un JSON anche in cartelle omonime diverse da quella del
    file media (es. lo stesso album "Foto da 2018" ripetuto in più parti
    "Takeout N" di un export diviso da Google)."""
    index = {}
    for p in input_root.rglob("*"):
        if should_stop is not None and should_stop():
            break
        if p.is_dir():
            index.setdefault(p.name, []).append(p)
    return index


def collect_media_files(input_root: Path, should_stop=None) -> list:
    files = []
    for p in input_root.rglob("*"):
        if should_stop is not None and should_stop():
            break
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


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dedupe_identical_files(media_files: list, should_stop=None, progress=None) -> tuple:
    """Una stessa foto/video che appartiene a più album di Google Foto viene
    esportata da Google Takeout una volta per ogni album: stesso nome, stesso
    contenuto, in cartelle diverse. Qui li individuiamo e ne teniamo solo
    una copia, per non finire con "foto.jpg", "foto_1.jpg", "foto_2.jpg" in
    output quando in realtà è sempre la stessa identica foto.

    Il confronto è in due fasi per essere certi al 100% che siano davvero
    lo stesso file, non solo un nome coincidente:
    1. Raggruppamento veloce per nome (case-insensitive) + dimensione in byte.
    2. Solo dentro questi gruppi "sospetti", calcolo di uno SHA-256 su tutto
       il contenuto: vengono trattati come duplicati solo i file con hash
       identico (zero rischio di falsi positivi).

    Ritorna (file_da_elaborare, coppie_scartate) dove coppie_scartate è una
    lista di (file_tenuto, file_scartato) per il report di trasparenza.

    `progress`, se passato, viene richiamato periodicamente come
    progress(controllati, totale_candidati): è il passaggio più lento (legge
    per intero ogni file candidato) e senza un riscontro visibile può durare
    a lungo su dischi esterni lenti, risultando indistinguibile da un blocco.
    """
    by_name_size = {}
    for p in media_files:
        try:
            size = p.stat().st_size
        except OSError:
            size = None
        by_name_size.setdefault((p.name.lower(), size), []).append(p)

    total_candidates = sum(len(g) for g in by_name_size.values() if len(g) > 1)
    checked = 0
    PROGRESS_EVERY = 50
    if progress is not None:
        progress(0, total_candidates)

    kept = []
    duplicates = []

    for group in by_name_size.values():
        # Interruzione cooperativa: questo è il passaggio più lento (lettura
        # completa del contenuto per il confronto), quindi il più importante
        # da poter fermare subito. I gruppi non ancora esaminati vengono
        # semplicemente tenuti così com'è (non deduplicati, ma nessun file
        # perso) invece di continuare a leggerne il contenuto.
        if should_stop is not None and should_stop():
            kept.extend(group)
            continue

        if len(group) == 1:
            kept.append(group[0])
            continue

        by_hash = {}
        stopped_mid_group = False
        for p in group:
            if should_stop is not None and should_stop():
                stopped_mid_group = True
                break
            try:
                digest = _file_hash(p)
            except OSError:
                # Illeggibile: non rischiamo di scartarlo, lo teniamo com'è.
                digest = f"__unreadable__{id(p)}"
            by_hash.setdefault(digest, []).append(p)
            checked += 1
            if progress is not None and checked % PROGRESS_EVERY == 0:
                progress(checked, total_candidates)

        if stopped_mid_group:
            kept.extend(group)
            continue

        for hash_group in by_hash.values():
            hash_group.sort(key=str)
            kept.append(hash_group[0])
            for extra in hash_group[1:]:
                duplicates.append((hash_group[0], extra))

    if progress is not None:
        progress(checked, total_candidates)

    return kept, duplicates


STRINGS = {
    "it": {
        "input_not_found": "Cartella di input non trovata: {path}",
        "scanning": "Scansione di {path} ...",
        "found_files": "Trovati {n} file media da elaborare.",
        "found_duplicates": (
            "{n} file duplicati (stesso contenuto, presenti in più album) "
            "trovati: ne verrà copiato uno solo per ciascuno."
        ),
        "duplicates_log": "Elenco duplicati scartati: {path}",
        "no_json": "[NO JSON] {name}",
        "exiftool_error": "[ERRORE exiftool] {name}: {err}",
        "exception": "[ECCEZIONE] {name}: {exc}",
        "done": "Elaborazione completata.",
        "error_log": "Log errori: {path}",
        "match_log": "Report abbinamenti file/JSON: {path}",
        "fatal_error": "[ERRORE FATALE] {exc}",
        "cancelled": "Elaborazione annullata dall'utente: i file già scritti sono stati mantenuti.",
        "insufficient_space": (
            "Spazio libero insufficiente nella cartella di output: servono "
            "circa {needed} ma ne risultano disponibili solo {available}. "
            "Nessun file è stato scritto."
        ),
    },
    "en": {
        "input_not_found": "Input folder not found: {path}",
        "scanning": "Scanning {path} ...",
        "found_files": "Found {n} media files to process.",
        "found_duplicates": (
            "{n} duplicate files found (identical content, present in "
            "multiple albums): only one copy of each will be kept."
        ),
        "duplicates_log": "Discarded duplicates list: {path}",
        "no_json": "[NO JSON] {name}",
        "exiftool_error": "[exiftool ERROR] {name}: {err}",
        "exception": "[EXCEPTION] {name}: {exc}",
        "done": "Processing complete.",
        "error_log": "Error log: {path}",
        "match_log": "File/JSON match report: {path}",
        "fatal_error": "[FATAL ERROR] {exc}",
        "cancelled": "Processing cancelled by the user: files already written were kept.",
        "insufficient_space": (
            "Not enough free space in the output folder: about {needed} "
            "needed, but only {available} available. No file was written."
        ),
    },
}


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024

MATCH_LOG_COLUMNS = ("file_media", "file_json", "file_destinazione")
DUPLICATES_LOG_COLUMNS = ("file_tenuto", "file_scartato")


class Job:
    """Rappresenta un'esecuzione del fixer, eseguita in un thread separato."""

    def __init__(self, input_dir: str, output_dir: str, dry_run: bool = False, jobs: int = 4,
                 lang: str = "it", fallback_tz: str = "UTC"):
        self.input_root = Path(input_dir).expanduser().resolve()
        self.output_root = Path(output_dir).expanduser().resolve()
        self.dry_run = dry_run
        self.jobs = max(1, jobs)
        self.strings = STRINGS.get(lang, STRINGS["it"])
        self.fallback_tz = fallback_tz

        self.state = "pending"  # pending -> scanning -> running -> done/error/cancelled
        self.total_raw = 0
        self.total = 0
        self.processed = 0
        self.missing_metadata = 0
        self.errors = 0
        self.duplicates_skipped = 0
        self.dedup_checked = 0
        self.dedup_total_candidates = 0
        self.log_lines = []
        self.error_message = None
        self.cancelled = False
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
                "total_raw": self.total_raw,
                "total": self.total,
                "processed": self.processed,
                "missing_metadata": self.missing_metadata,
                "errors": self.errors,
                "duplicates_skipped": self.duplicates_skipped,
                "dedup_checked": self.dedup_checked,
                "dedup_total_candidates": self.dedup_total_candidates,
                "error_message": self.error_message,
                "log_tail": self.log_lines[-200:],
            }

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        """Richiede l'interruzione cooperativa della run: i file non ancora
        iniziati vengono saltati, quelli già in corso di copia/scrittura
        vengono comunque portati a termine (non si interrompe mai un file
        a metà), e nessun file già scritto viene toccato o rimosso."""
        self.cancelled = True

    def _run(self):
        try:
            if not self.input_root.is_dir():
                raise RuntimeError(self.t("input_not_found", path=self.input_root))

            self.output_root.mkdir(parents=True, exist_ok=True)
            error_log_path = self.output_root / "errors.log"
            error_log_path.write_text("", encoding="utf-8")

            match_log_path = self.output_root / "abbinamenti.csv"
            with open(match_log_path, "w", encoding="utf-8", newline="") as mf:
                csv.writer(mf).writerow(MATCH_LOG_COLUMNS)

            duplicates_log_path = self.output_root / "duplicati.csv"
            with open(duplicates_log_path, "w", encoding="utf-8", newline="") as df:
                csv.writer(df).writerow(DUPLICATES_LOG_COLUMNS)

            should_stop = lambda: self.cancelled

            self.state = "scanning"
            self.log(self.t("scanning", path=self.input_root))
            media_files = collect_media_files(self.input_root, should_stop=should_stop)
            self.total_raw = len(media_files)
            self.log(self.t("found_files", n=len(media_files)))

            # Una stessa foto/video che appartiene a più album di Google Foto
            # viene esportata da Google una volta per ogni album: stesso
            # contenuto, cartelle diverse. Le individuiamo (per nome+dimensione,
            # poi confermate byte-per-byte con SHA-256) e ne teniamo una sola
            # copia, altrimenti finirebbero in output come "foto.jpg",
            # "foto_1.jpg", "foto_2.jpg" pur essendo la stessa identica foto.
            # È il passaggio più lento (legge il contenuto dei file), quindi
            # anche il più importante da rendere interrompibile: se l'utente
            # annulla mentre è in corso, i gruppi non ancora esaminati
            # vengono lasciati così com'è invece di continuare a leggerli.
            def _dedup_progress(checked, total):
                self.dedup_checked = checked
                self.dedup_total_candidates = total

            media_files, duplicate_pairs = dedupe_identical_files(
                media_files, should_stop=should_stop, progress=_dedup_progress,
            )
            self.duplicates_skipped = len(duplicate_pairs)
            if duplicate_pairs:
                self.log(self.t("found_duplicates", n=self.duplicates_skipped))
                with open(duplicates_log_path, "a", encoding="utf-8", newline="") as df:
                    writer = csv.writer(df)
                    for kept, skipped in duplicate_pairs:
                        writer.writerow([str(kept), str(skipped)])
                self.log(self.t("duplicates_log", path=duplicates_log_path))

            self.total = len(media_files)

            dir_name_index = {}
            if not self.cancelled:
                if not self.dry_run:
                    needed = 0
                    for mf in media_files:
                        try:
                            needed += mf.stat().st_size
                        except OSError:
                            pass
                    available = shutil.disk_usage(self.output_root).free
                    if available < needed:
                        raise RuntimeError(self.t(
                            "insufficient_space",
                            needed=_format_size(needed),
                            available=_format_size(available),
                        ))

                dir_name_index = build_dir_name_index(self.input_root, should_stop=should_stop)

            self.state = "running"
            dir_json_cache = {}
            dir_sibling_cache = {}
            cache_lock = threading.Lock()
            error_log_lock = threading.Lock()
            match_log_lock = threading.Lock()

            from concurrent.futures import ThreadPoolExecutor, as_completed

            def process_one(media_path: Path):
                if self.cancelled:
                    # Interruzione cooperativa: i file non ancora avviati
                    # vengono saltati senza contarli né come processati né
                    # come errori; quelli già in corso (già dentro questa
                    # funzione) proseguono fino in fondo.
                    return
                try:
                    with cache_lock:
                        json_path = find_json_for_media(media_path, dir_json_cache, dir_sibling_cache, dir_name_index)

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

                        with match_log_lock:
                            with open(match_log_path, "a", encoding="utf-8", newline="") as mf:
                                csv.writer(mf).writerow([
                                    str(media_path),
                                    str(json_path) if json_path is not None else "",
                                    str(dest_path),
                                ])

                        if has_metadata:
                            exif_args = build_exiftool_args(meta, self.fallback_tz)
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

            if not self.cancelled:
                with ThreadPoolExecutor(max_workers=self.jobs) as executor:
                    futures = [executor.submit(process_one, mf) for mf in media_files]
                    for _ in as_completed(futures):
                        pass

            if self.cancelled:
                self.log(self.t("cancelled"))
                self.log(self.t("error_log", path=error_log_path))
                if not self.dry_run:
                    self.log(self.t("match_log", path=match_log_path))
                self.state = "cancelled"
            else:
                self.log(self.t("done"))
                self.log(self.t("error_log", path=error_log_path))
                if not self.dry_run:
                    self.log(self.t("match_log", path=match_log_path))
                self.state = "done"

        except Exception as exc:
            self.error_message = str(exc)
            self.state = "error"
            self.log(self.t("fatal_error", exc=exc))
