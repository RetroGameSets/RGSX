#!/usr/bin/env python3
import os
# Force headless mode before any project imports
os.environ.setdefault("RGSX_HEADLESS", "1")
import sys
import argparse
import asyncio
import json
import logging
import requests
import time
import zipfile
import shutil
import re

# IMPORTANT: Avoid importing display/pygame modules for headless mode
import config  # paths, settings, SAVE_FOLDER, etc.
import network as network_mod  # for progress_queues access
from utils import load_sources, load_games, is_extension_supported, load_extensions_json, sanitize_filename, extract_zip_data
from history import load_history, save_history, add_to_history
from network import download_rom, download_from_1fichier, is_1fichier_url
from rgsx_settings import get_sources_zip_url

logger = logging.getLogger("rgsx.cli")


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format='%(levelname)s: %(message)s')


def ensure_data_present(verbose: bool = False):
    """Ensure systems list and games data exist; if missing, download OTA data ZIP and extract it."""
    # If systems_list exists and games folder has some json files, nothing to do
    has_sources = os.path.exists(config.SOURCES_FILE)
    has_games = os.path.isdir(config.GAMES_FOLDER) and any(
        f.lower().endswith('.json') for f in os.listdir(config.GAMES_FOLDER)
    )
    if has_sources and has_games:
        return True

    url = get_sources_zip_url(config.OTA_data_ZIP)
    if not url:
        print("No sources URL configured; cannot auto-download data.", file=sys.stderr)
        return False

    zip_path = os.path.join(config.SAVE_FOLDER, "data_download.zip")
    os.makedirs(config.SAVE_FOLDER, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    # Always show progress when we're in the 'missing data' path
    show = True or verbose
    print("Source data not found, downloading...")
    print(f"Downloading data from {url}...")
    try:
        with requests.get(url, stream=True, headers=headers, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            last_t = time.time()
            last_d = 0
            last_line = ""
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show and total:
                        now = time.time()
                        dt = max(1e-6, now - last_t)
                        delta = downloaded - last_d
                        speed = delta / dt / (1024*1024)
                        pct = int(downloaded/total*100)
                        mb = downloaded/(1024*1024)
                        tot = total/(1024*1024)
                        line = f"Downloading data: {pct:3d}% ({mb:.1f}/{tot:.1f} MB) @ {speed:.1f} MB/s"
                        if line != last_line:
                            print("\r" + line, end="", flush=True)
                            last_line = line
                        last_t = now
                        last_d = downloaded
        if show:
            print()
    except Exception as e:
        print(f"Failed to download data: {e}", file=sys.stderr)
        return False

    # Extract
    if show:
        print("Extracting data...")
    try:
        # Custom extraction with progress
        total_size = 0
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            total_size = sum(info.file_size for info in zip_ref.infolist() if not info.is_dir())
        extracted = 0
        chunk = 2048
        last_line = ""
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for info in zip_ref.infolist():
                if info.is_dir():
                    continue
                file_path = os.path.join(config.SAVE_FOLDER, info.filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with zip_ref.open(info) as src, open(file_path, 'wb') as dst:
                    remaining = info.file_size
                    while remaining > 0:
                        buf = src.read(min(chunk, remaining))
                        if not buf:
                            break
                        dst.write(buf)
                        remaining -= len(buf)
                        extracted += len(buf)
                        if show and total_size:
                            pct = int(extracted/total_size*100)
                            mb = extracted/(1024*1024)
                            tot = total_size/(1024*1024)
                            line = f"Extracting data: {pct:3d}% ({mb:.1f}/{tot:.1f} MB)"
                            if line != last_line:
                                print("\r" + line, end="", flush=True)
                                last_line = line
                try:
                    os.chmod(file_path, 0o644)
                except Exception:
                    pass
        if show and last_line:
            print()
        ok, msg = True, "OK"
    except Exception as ee:
        ok, msg = False, str(ee)
    try:
        if os.path.exists(zip_path):
            os.remove(zip_path)
    except Exception:
        pass
    if not ok:
        print(f"Failed to extract data: {msg}", file=sys.stderr)
        return False
    if show:
        print("Data downloaded and extracted.")
    return True


def cmd_platforms(args):
    ensure_data_present(getattr(args, 'verbose', False))
    sources = load_sources()
    items = []
    for s in sources:
        name = s.get("platform_name") or s.get("name") or s.get("platform") or ""
        folder = s.get("folder") or s.get("dossier") or ""
        if name:
            items.append({"name": name, "folder": folder})
    if getattr(args, 'json', False):
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for it in items:
            # name TAB folder (folder may be empty for BIOS/virtual)
            print(f"{it['name']}\t{it['folder']}")


def _resolve_platform(sources, platform_name: str):
    # match by display name or key, case-insensitive
    pn = platform_name.strip().lower()
    for s in sources:
        display = (s.get("platform_name") or s.get("name") or "").lower()
        key = (s.get("platform") or s.get("folder") or "").lower()
        if pn == display or pn == key:
            return s
    # fallback: substring
    for s in sources:
        display = (s.get("platform_name") or s.get("name") or "").lower()
        if pn in display:
            return s
    return None


def cmd_games(args):
    ensure_data_present(getattr(args, 'verbose', False))
    sources = load_sources()
    platform = _resolve_platform(sources, args.platform)
    if not platform:
        print(f"Platform not found: {args.platform}", file=sys.stderr)
        sys.exit(2)
    platform_id = (
        platform.get('platform_name')
        or platform.get('platform')
        or platform.get('folder')
        or args.platform
    )
    games = load_games(platform_id)
    if args.search:
        q = args.search.lower()
        games = [g for g in games if q in (g[0] or '').lower()]
    for g in games:
        # games items can be (name, url) or (name, url, size)
        title = g[0] if isinstance(g, (list, tuple)) and g else str(g)
        print(title)


def cmd_history(args):
    hist = load_history()
    if args.json:
        print(json.dumps(hist, ensure_ascii=False, indent=2))
    else:
        for e in hist[-args.tail:]:
            print(f"[{e.get('status')}] {e.get('platform')} - {e.get('game_name')} ({e.get('progress','?')}%) {e.get('message','')}")


def cmd_clear_history(args):
    save_history([])
    print("History cleared")


async def _run_download_with_progress(url: str, platform_name: str, game_name: str, force_extract_zip: bool = False):
    """Run download and display live progress in the terminal."""
    task_id = f"cli-{os.getpid()}"
    # Start download coroutine
    coro = download_from_1fichier(url, platform_name, game_name, force_extract_zip, task_id) if is_1fichier_url(url) else download_rom(url, platform_name, game_name, force_extract_zip, task_id)
    task = asyncio.create_task(coro)

    last_line = ""
    def print_progress(pct: int, speed_mb_s: float | None, downloaded: int, total: int):
        nonlocal last_line
        # Build a concise one-line status
        total_mb = total / (1024*1024) if total else 0
        dl_mb = downloaded / (1024*1024)
        spd = f" @ {speed_mb_s:.1f} MB/s" if speed_mb_s is not None and speed_mb_s > 0 else ""
        line = f"Downloading: {pct:3d}% ({dl_mb:.1f}/{total_mb:.1f} MB){spd}"
        # Avoid overly chatty output
        if line != last_line:
            print("\r" + line, end="", flush=True)
            last_line = line

    # Poll shared in-memory history for progress (non-intrusive)
    while not task.done():
        try:
            if isinstance(config.history, list):
                for e in config.history:
                    if e.get('url') == url and e.get('status') in ("downloading", "Téléchargement", "Extracting"):
                        downloaded = int(e.get('downloaded_size') or 0)
                        total = int(e.get('total_size') or 0)
                        speed = e.get('speed')
                        if total > 0:
                            pct = int(downloaded/total*100)
                        else:
                            pct = 0
                        # speed might be None or 0 when unknown
                        print_progress(pct, float(speed) if isinstance(speed, (int, float)) else None, downloaded, total)
                        break
        except Exception:
            pass
        await asyncio.sleep(0.2)

    success, message = await task
    if last_line:
        # End the progress line
        print()
    if success:
        print(message or "Download completed")
        return 0
    else:
        print(message or "Download failed", file=sys.stderr)
        return 1


def cmd_download(args):
    ensure_data_present(getattr(args, 'verbose', False))
    sources = load_sources()
    platform = _resolve_platform(sources, args.platform)
    if not platform:
        print(f"Platform not found: {args.platform}", file=sys.stderr)
        sys.exit(2)
    platform_id = (
        platform.get('platform_name')
        or platform.get('platform')
        or platform.get('folder')
        or args.platform
    )
    games = load_games(platform_id)
    query_raw = args.game.strip()

    def _strip_ext(name: str) -> str:
        try:
            base, _ = os.path.splitext(name)
            return base
        except Exception:
            return name

    def _tokens(s: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", s.lower())

    def _game_title(g) -> str | None:
        return g[0] if isinstance(g, (list, tuple)) and g else None

    def _game_url(g) -> str | None:
        return g[1] if isinstance(g, (list, tuple)) and len(g) > 1 else None

    # 1) Exact match (case-insensitive), with and without extension
    match = None
    q_lower = query_raw.lower()
    q_no_ext = _strip_ext(query_raw).lower()
    for g in games:
        title = _game_title(g)
        if not title:
            continue
        t_lower = title.strip().lower()
        if t_lower == q_lower or _strip_ext(t_lower) == q_no_ext:
            match = (title, _game_url(g))
            break

    # Si pas d'exact, ne pas auto-sélectionner; proposer des correspondances possibles
    suggestions = []  # (priority, score, title, url)
    if not match:
        # 2) Sous-chaîne sur le titre (ou sans extension)
        for g in games:
            title = _game_title(g)
            if not title:
                continue
            t_lower = title.lower()
            t_no_ext = _strip_ext(t_lower)
            pos_full = t_lower.find(q_lower)
            pos_noext = t_no_ext.find(q_no_ext)
            if pos_full != -1 or (q_no_ext and pos_noext != -1):
                # priorité 0 = sous-chaîne; score = position trouvée (plus petit est mieux)
                pos = pos_full if pos_full != -1 else pos_noext
                suggestions.append((0, max(0, pos), title, _game_url(g)))

        # 3) Tokens en ordre non-contigu, avec score de proximité
        def ordered_gap_score(qt: list[str], tt: list[str]):
            pos = []
            start = 0
            for tok in qt:
                try:
                    i = next(i for i in range(start, len(tt)) if tt[i] == tok)
                except StopIteration:
                    return None
                pos.append(i)
                start = i + 1
            gap = (pos[-1] - pos[0]) - (len(qt) - 1)
            return max(0, gap)

        q_tokens = _tokens(query_raw)
        if q_tokens:
            for g in games:
                title = _game_title(g)
                if not title:
                    continue
                tt = _tokens(title)
                score = ordered_gap_score(q_tokens, tt)
                if score is not None:
                    suggestions.append((1, score, title, _game_url(g)))

        # 4) Tokens présents (ordre libre)
        if q_tokens:
            for g in games:
                title = _game_title(g)
                if not title:
                    continue
                t_tokens = set(_tokens(title))
                if all(tok in t_tokens for tok in q_tokens):
                    suggestions.append((2, len(t_tokens), title, _game_url(g)))

        # Dédupliquer en gardant la meilleure (priorité/score) pour chaque titre
        best_by_title = {}
        for prio, score, title, url in suggestions:
            key = title.lower()
            cur = best_by_title.get(key)
            if cur is None or (prio, score) < (cur[0], cur[1]):
                best_by_title[key] = (prio, score, title, url)
        suggestions = sorted(best_by_title.values(), key=lambda x: (x[0], x[1], x[2].lower()))
    if not match:
        # Afficher les correspondances possibles, et en mode interactif proposer un choix
        print(f"No exact result found for this game: {args.game}")
        if suggestions:
            limit = 20
            shown = suggestions[:limit]
            # Mode interactif par défaut si TTY détecté, ou si --interactive explicite
            interactive = False
            try:
                interactive = bool(getattr(args, 'interactive', False) or sys.stdin.isatty())
            except Exception:
                interactive = bool(getattr(args, 'interactive', False))
            if interactive:
                print("Select a match to download:")
                for i, s in enumerate(shown, start=1):
                    print(f"  {i}. {s[2]}")
                if len(suggestions) > limit:
                    print(f"  ... and {len(suggestions) - limit} more not shown")
                try:
                    choice = input("Enter number (or press Enter to cancel): ").strip()
                except EOFError:
                    choice = ""
                if choice:
                    try:
                        idx = int(choice)
                        if 1 <= idx <= len(shown):
                            sel = shown[idx-1]
                            match = (sel[2], sel[3])
                    except Exception:
                        pass
            if not match:
                print("Here are potential matches (use the exact title with --game):")
                for i, s in enumerate(shown, start=1):
                    print(f"  {i}. {s[2]}")
                if len(suggestions) > limit:
                    print(f"  ... and {len(suggestions) - limit} more")
                print("Tip: list games with: python rgsx_cli.py games --platform \"%s\" --search \"%s\"" % (args.platform, query_raw))
                sys.exit(3)
        else:
            print("No similar titles found.")
            print("Tip: list games with: python rgsx_cli.py games --platform \"%s\" --search \"%s\"" % (args.platform, query_raw))
            sys.exit(3)

    title, url = match
    # Determine if we should force ZIP extraction (only when we can safely check extensions)
    is_zip_non_supported = False
    exts = None
    try:
        if os.path.exists(config.JSON_EXTENSIONS) and os.path.getsize(config.JSON_EXTENSIONS) > 2:
            exts = load_extensions_json()
    except Exception:
        exts = None
    if exts is not None:
        # If extension unsupported for this platform, either block or allow with --force
        if not is_extension_supported(sanitize_filename(title), platform.get('platform') or '', exts):
            import os as _os
            ext = _os.path.splitext(title)[1].lower()
            is_zip_non_supported = ext in ('.zip', '.rar')
            if not args.force and not is_zip_non_supported:
                print("Unsupported extension for this platform. Use --force to override.", file=sys.stderr)
                sys.exit(4)

    # Add entry to history and run
    hist = load_history()
    hist.append({
        "platform": platform.get('platform_name') or platform.get('platform') or args.platform,
        "game_name": title,
        "status": "downloading",
        "url": url,
        "progress": 0,
        "message": "Téléchargement en cours",
        "timestamp": None,
    })
    save_history(hist)
    # Important: share the same list object with network module so it can update history in place
    try:
        config.history = hist
    except Exception:
        pass

    # Run download with live progress
    exit_code = asyncio.run(_run_download_with_progress(url, platform_id, title, is_zip_non_supported))
    if exit_code != 0:
        sys.exit(exit_code)


def build_parser():
    p = argparse.ArgumentParser(prog="rgsx-cli", description="RGSX headless CLI")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    p.add_argument("--force-update", "-force-update", action="store_true", help="Purge data (games/images/systems_list) and redownload")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("platforms", help="List available platforms")
    sp.add_argument("--json", action="store_true", help="Output JSON with name and folder")
    # Also accept global flags after the subcommand
    sp.add_argument("--verbose", action="store_true", help="Verbose logging")
    sp.add_argument("--force-update", "-force-update", action="store_true", help="Purge data (games/images/systems_list) and redownload")
    sp.set_defaults(func=cmd_platforms)

    sg = sub.add_parser("games", help="List games for a platform")
    sg.add_argument("--platform", required=True, help="Platform name or key")
    sg.add_argument("--search", help="Filter by name contains")
    # Also accept global flags after the subcommand
    sg.add_argument("--verbose", action="store_true", help="Verbose logging")
    sg.add_argument("--force-update", "-force-update", action="store_true", help="Purge data (games/images/systems_list) and redownload")
    sg.set_defaults(func=cmd_games)

    sd = sub.add_parser("download", help="Download a game by title")
    sd.add_argument("--platform", required=True)
    sd.add_argument("--game", required=True)
    sd.add_argument("--force", action="store_true", help="Override unsupported extension warning")
    sd.add_argument("--interactive", "-i", action="store_true", help="Prompt to choose from matches when no exact title is found")
    # Also accept global flags after the subcommand
    sd.add_argument("--verbose", action="store_true", help="Verbose logging")
    sd.add_argument("--force-update", "-force-update", action="store_true", help="Purge data (games/images/systems_list) and redownload")
    sd.set_defaults(func=cmd_download)

    sh = sub.add_parser("history", help="Show recent history")
    sh.add_argument("--tail", type=int, default=50, help="Last N entries")
    sh.add_argument("--json", action="store_true")
    # Also accept global flags after the subcommand
    sh.add_argument("--verbose", action="store_true", help="Verbose logging")
    sh.add_argument("--force-update", "-force-update", action="store_true", help="Purge data (games/images/systems_list) and redownload")
    sh.set_defaults(func=cmd_history)

    sc = sub.add_parser("clear-history", help="Clear history")
    # Also accept global flags after the subcommand
    sc.add_argument("--verbose", action="store_true", help="Verbose logging")
    sc.add_argument("--force-update", "-force-update", action="store_true", help="Purge data (games/images/systems_list) and redownload")
    sc.set_defaults(func=cmd_clear_history)

    return p


def main(argv=None):
    argv = argv or sys.argv[1:]
    # Force headless mode for CLI
    os.environ.setdefault("RGSX_HEADLESS", "1")
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    # Ensure SAVE_FOLDER exists (for history/download outputs, etc.)
    try:
        os.makedirs(config.SAVE_FOLDER, exist_ok=True)
    except Exception:
        pass

    # Handle global force-update (can run without a subcommand)
    if getattr(args, 'force_update', False):
        # Purge
        try:
            if os.path.exists(config.SOURCES_FILE):
                os.remove(config.SOURCES_FILE)
        except Exception:
            pass
        try:
            shutil.rmtree(config.GAMES_FOLDER, ignore_errors=True)
        except Exception:
            pass
        try:
            shutil.rmtree(config.IMAGES_FOLDER, ignore_errors=True)
        except Exception:
            pass
        # Redownload
        ok = ensure_data_present(verbose=True)
        if not ok:
            sys.exit(1)
        # If no subcommand, exit now
        if not getattr(args, 'cmd', None):
            return

    # If a subcommand is provided, run it
    if getattr(args, 'cmd', None):
        args.func(args)


if __name__ == "__main__":
    main()
