"""Download size, in MB, for every game in the Releases catalog.

A game is rarely one file: a .m3u drags in the discs it lists, a .psn drags in a save directory
somewhere else entirely, a mame .zip drags in a same-named directory. The size shown in the
catalog has to be the size of everything the download will actually transfer, so the rules here
mirror the file list built in downloads.py — if they drift apart the catalog lies about the size.

Sizes are computed per snapshot and cached on disk. Releases ROMs live in a ZFS snapshot, which is
read-only, so a system's sizes can only change when it publishes a new snapshot version. A refresh
therefore only pays for the systems whose version moved; the rest are read back from the cache.

Within a system we walk the snapshot once and answer every game from that in-memory tree, rather
than stat'ing each game's files as we go: a walk costs one stat per file, while the per-game rules
would stat popular directories (mame's, singe's frameworks) over and over.
"""
import json
import logging
import os
import re
from typing import Dict, Optional, Set

from app.services.download import (
    parse_acgame_file,
    parse_cue_file,
    parse_m3u_file,
    parse_m3u_ps3_directory,
    parse_psn_file,
    parse_psvita_file,
    parse_xbox360_file,
    WIN98_SAVES_DIRNAME,
    win98_saves_dir,
)

logger = logging.getLogger(__name__)

CACHE_VERSION = 1

# Systems whose ROM ships with everything else in its directory (soundtrack packs)
MSU_SYSTEMS = ('msu-md', 'nes-msu', 'snes-msu1')
# ...except these, which are self-contained archives
MSU_SELF_CONTAINED_EXTS = ('.squashfs', '.wsquashfs')
# Systems where a .zip ROM is accompanied by a same-named directory
ZIP_WITH_DIR_SYSTEMS = ('namco2x6', 'mame', 'mame_lite', 'naomi', 'naomi2')
SINGE_FRAMEWORK_DIRS = ('Framework', 'FrameworkCustom_1', 'FrameworkKimmy', 'KimmyScript')

PS3_SAVES_SUBPATH = ('_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game')
PSVITA_SAVES_SUBPATH = ('_saves_', 'psvita', 'vita3k', 'ux0', 'app')

_UNIFIED_KEY_RE = re.compile(r'^(.*?)\.\(([^|]+)\|([^)]+)\)$')

# Artwork, videos and manuals sit in media/ at the snapshot root, alongside the ROMs. A download
# never transfers them, and there are ~10 of them per game, so walking media/ would cost an order
# of magnitude more stats than the ROMs we actually came for. It dwarfs everything else in a
# snapshot, so it is pruned at the root rather than filtered per file.
SNAPSHOT_SKIP_ROOT_DIRS = frozenset({'media'})


class _Tree:
    """Every file under one directory, from a single walk.

    Beyond per-file sizes we keep recursive and direct-children totals per directory, so the
    "download this whole directory" rules are a dict lookup instead of another walk.
    """

    def __init__(self, skip_root_dirs: frozenset = frozenset()) -> None:
        self.files: Dict[str, int] = {}          # 'sub/game.zip' -> bytes
        self.dirs: Set[str] = set()              # 'sub' ('' is the root)
        self.dir_total: Dict[str, int] = {}      # 'sub' -> bytes of everything below it
        self.dir_direct: Dict[str, int] = {}     # 'sub' -> bytes of the files directly in it
        self._skip_root_dirs = skip_root_dirs

    def _add(self, rel_dir: str, name: str, size: int) -> None:
        rel = f"{rel_dir}/{name}" if rel_dir else name
        self.files[rel] = size
        self.dir_direct[rel_dir] = self.dir_direct.get(rel_dir, 0) + size
        # Charge the file to every directory above it, so dir_total is ready to read later
        d = rel_dir
        while True:
            self.dir_total[d] = self.dir_total.get(d, 0) + size
            if not d:
                break
            d = d.rsplit('/', 1)[0] if '/' in d else ''

    def scan(self, root: str, rel_dir: str = '') -> None:
        self.dirs.add(rel_dir)
        self.dir_total.setdefault(rel_dir, 0)
        try:
            entries = list(os.scandir(root))
        except OSError as e:
            logger.warning(f"Could not scan {root}: {e}")
            return
        for entry in entries:
            try:
                if entry.is_dir():
                    if not rel_dir and entry.name.lower() in self._skip_root_dirs:
                        continue
                    child_rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                    self.scan(entry.path, child_rel)
                elif entry.is_file():
                    self._add(rel_dir, entry.name, entry.stat().st_size)
            except OSError as e:
                logger.debug(f"Skipping unreadable entry {entry.path}: {e}")


def _scan_tree(root: str, skip_root_dirs: frozenset = frozenset()) -> Optional[_Tree]:
    if not os.path.isdir(root):
        return None
    tree = _Tree(skip_root_dirs)
    tree.scan(root)
    return tree


class _SaveTrees:
    """The save directories games pull in, scanned at most once each per refresh.

    Saves live outside the snapshot — under GAMES_PATH/_saves_/, except win98's, which sit in the
    system directory — and downloads read them live, so they are scanned lazily and only for the
    systems that actually reference them.
    """

    def __init__(self, games_path: str) -> None:
        self._games_path = games_path
        self._cache: Dict[str, Optional[_Tree]] = {}

    def _get(self, subpath) -> Optional[_Tree]:
        key = '/'.join(subpath)
        if key not in self._cache:
            self._cache[key] = _scan_tree(os.path.join(self._games_path, *subpath))
        return self._cache[key]

    def ps3(self) -> Optional[_Tree]:
        return self._get(PS3_SAVES_SUBPATH)

    def psvita(self) -> Optional[_Tree]:
        return self._get(PSVITA_SAVES_SUBPATH)

    def win98(self) -> Optional[_Tree]:
        # Not a fixed subpath: the directory moved into the system, with a fallback while the
        # files are being moved, so downloads.py resolves it and the size has to follow.
        if 'win98' not in self._cache:
            self._cache['win98'] = _scan_tree(win98_saves_dir(self._games_path))
        return self._cache['win98']


def _parent_dir(rel: str) -> str:
    return rel.rsplit('/', 1)[0] if '/' in rel else ''


def _join_rel(rel_dir: str, rel_file: str) -> str:
    """Resolve a path relative to rel_dir into a tree key, or '' if it escapes the tree."""
    joined = os.path.normpath(f"{rel_dir}/{rel_file}" if rel_dir else rel_file)
    joined = joined.replace('\\', '/')
    if joined.startswith('..') or os.path.isabs(joined):
        return ''
    return joined


def _resolve_rompath(rompath: str, tree: _Tree) -> Optional[str]:
    """Map a catalog key to a path in the snapshot.

    Unified keys ("game.(z64|n64)") stand for whichever of the two ROMs the client's platform
    wants; both are the same game, so the size is taken from whichever one is present.
    """
    if rompath in tree.files or rompath in tree.dirs:
        return rompath
    match = _UNIFIED_KEY_RE.match(rompath)
    if match:
        base, ext1, ext2 = match.group(1), match.group(2), match.group(3)
        for candidate in (f"{base}.{ext1}", f"{base}.{ext2}"):
            if candidate in tree.files or candidate in tree.dirs:
                return candidate
    return None


def _save_dir_bytes(tree: Optional[_Tree], directory_name: Optional[str]) -> int:
    if not tree or not directory_name:
        return 0
    return tree.dir_total.get(directory_name, 0)


def _win98_stem_bytes(tree: _Tree, prefix: str, stem: str) -> int:
    """The saves matching one ROM, among the files sitting directly in prefix."""
    total = tree.files.get(f"{prefix}{stem}.pure.zip", 0)
    sav_re = re.compile(f"^{re.escape(stem)}-\\S+\\.sav$")
    for name, size in tree.files.items():
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if '/' not in rest and sav_re.match(rest):
            total += size
    return total


def _win98_saves_bytes(tree: _Tree, saves: _SaveTrees, rom_rel: str) -> int:
    """The .pure.zip and -*.sav files win98 downloads alongside the ROM.

    A snapshot taken since the saves moved into the system directory carries its own _saves_/ and
    the download reads the release's saves from there; older snapshots have none and fall back to
    the live directory, so the size falls back with it.
    """
    stem = os.path.splitext(os.path.basename(rom_rel))[0]
    if WIN98_SAVES_DIRNAME in tree.dirs:
        return _win98_stem_bytes(tree, f"{WIN98_SAVES_DIRNAME}/", stem)
    live = saves.win98()
    return _win98_stem_bytes(live, '', stem) if live else 0


def _sum_listed_files(tree: _Tree, rel_dir: str, rel_files) -> int:
    """Total of files a .m3u/.cue names, resolved relative to the playlist's own directory."""
    total = 0
    seen = set()
    for rel_file in rel_files:
        key = _join_rel(rel_dir, rel_file.replace('\\', '/'))
        if not key or key in seen:
            continue
        seen.add(key)
        total += tree.files.get(key, 0)
    return total


def _game_size_bytes(
    system_id: str,
    rom_rel: str,
    snapshot_root: str,
    tree: _Tree,
    saves: _SaveTrees,
) -> int:
    """Bytes a download of this game transfers. Mirrors the file list built in downloads.py."""
    system = system_id.lower()
    rel_dir = _parent_dir(rom_rel)

    if rom_rel in tree.dirs:
        # A game that is itself a directory: everything under it
        total = tree.dir_total.get(rom_rel, 0)
        if system == 'singe':
            # Framework directories at the system root ship with every singe game
            for dir_name in SINGE_FRAMEWORK_DIRS:
                total += tree.dir_total.get(dir_name, 0)
        return total

    own_size = tree.files.get(rom_rel, 0)
    lower = rom_rel.lower()
    # Full path is only needed to read the handful of files that name their companions
    full_path = os.path.join(snapshot_root, rom_rel)

    if system == 'win98' and lower.endswith('.zip'):
        return own_size + _win98_saves_bytes(tree, saves, rom_rel)

    if lower.endswith('.m3u'):
        if system == 'ps3':
            # PS3 playlists point at a save directory rather than at sibling discs
            return own_size + _save_dir_bytes(saves.ps3(), parse_m3u_ps3_directory(full_path))
        return own_size + _sum_listed_files(tree, rel_dir, parse_m3u_file(full_path)[1:])

    if lower.endswith('.cue'):
        return own_size + _sum_listed_files(tree, rel_dir, parse_cue_file(full_path)[1:])

    if lower.endswith('.xbox360'):
        directory_name = parse_xbox360_file(full_path)
        if directory_name:
            return own_size + tree.dir_total.get(_join_rel(rel_dir, directory_name), 0)
        return own_size

    if lower.endswith('.acgame'):
        # The descriptor names a data directory sitting next to it
        directory_name = parse_acgame_file(full_path)
        if directory_name:
            return own_size + tree.dir_total.get(_join_rel(rel_dir, directory_name), 0)
        return own_size

    if lower.endswith('.psvita'):
        return own_size + _save_dir_bytes(saves.psvita(), parse_psvita_file(full_path))

    if system in MSU_SYSTEMS and not lower.endswith(MSU_SELF_CONTAINED_EXTS):
        # The whole soundtrack sits next to the ROM; subdirectories are not part of it
        return tree.dir_direct.get(rel_dir, 0)

    if lower.endswith('.psn'):
        return own_size + _save_dir_bytes(saves.ps3(), parse_psn_file(full_path))

    if system in ZIP_WITH_DIR_SYSTEMS and lower.endswith('.zip'):
        return own_size + tree.dir_total.get(rom_rel[: -len('.zip')], 0)

    if system == 'singe':
        total = own_size
        for dir_name in SINGE_FRAMEWORK_DIRS:
            total += tree.dir_total.get(_join_rel(rel_dir, dir_name), 0)
        return total

    return own_size


def _to_mb(size_bytes: int) -> float:
    return round(size_bytes / (1024 * 1024), 2)


def _compute_system_sizes(
    game_service,
    system_id: str,
    snapshot_dir_path: str,
    saves: _SaveTrees,
) -> Dict[str, float]:
    """Size in MB for every game of one system, from a single walk of its snapshot."""
    snapshot_root = os.path.join(game_service.games_path, system_id, snapshot_dir_path)
    tree = _scan_tree(snapshot_root, SNAPSHOT_SKIP_ROOT_DIRS)
    if tree is None:
        logger.warning(f"Snapshot directory not found for {system_id}: {snapshot_root}")
        return {}

    sizes: Dict[str, float] = {}
    missing = 0
    for rompath in game_service.catalog_releases.get(system_id, {}):
        resolved = _resolve_rompath(rompath, tree)
        if resolved is None:
            missing += 1
            continue
        sizes[rompath] = _to_mb(_game_size_bytes(system_id, resolved, snapshot_root, tree, saves))

    if missing:
        logger.info(f"{system_id}: {missing} catalog games have no file in the snapshot, size omitted")
    return sizes


def _cache_file_path(game_service) -> str:
    """Sit next to the catalog pickle, so both caches are wiped together."""
    return os.path.join(os.path.dirname(game_service._get_catalog_file_path()), 'release_sizes.json')


def _load_cache(path: str) -> Dict[str, dict]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read release size cache, recomputing: {e}")
        return {}
    if not isinstance(data, dict) or data.get('version') != CACHE_VERSION:
        logger.info("Release size cache is from an older format, recomputing")
        return {}
    return data.get('systems', {})


def _save_cache(path: str, systems: Dict[str, dict]) -> None:
    try:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({'version': CACHE_VERSION, 'systems': systems}, f)
        os.replace(tmp_path, path)
    except OSError as e:
        logger.warning(f"Could not write release size cache: {e}")


def compute_and_merge_release_sizes(game_service) -> int:
    """Set 'size_mb' on every game of the Releases catalog, reusing unchanged snapshots.

    Returns the number of games given a size.
    """
    if not game_service.games_path:
        logger.warning("GAMES_PATH not configured, skipping release size computation")
        return 0

    cache_path = _cache_file_path(game_service)
    cached = _load_cache(cache_path)
    saves = _SaveTrees(game_service.games_path)

    fresh: Dict[str, dict] = {}
    sized_count = 0
    reused_systems = 0

    for system_id in game_service.catalog_releases:
        version = game_service.system_versions.get(system_id)
        snapshot_dir_path = game_service.system_snapshot_paths.get(system_id)
        if not version or not snapshot_dir_path:
            logger.debug(f"No snapshot info for {system_id}, skipping size computation")
            continue

        entry = cached.get(system_id)
        if entry and entry.get('snapshot') == version and isinstance(entry.get('sizes'), dict):
            # Snapshots are read-only: same version means the same bytes on disk
            sizes = entry['sizes']
            reused_systems += 1
        else:
            logger.info(f"Computing release sizes for {system_id} (snapshot {version})...")
            sizes = _compute_system_sizes(game_service, system_id, snapshot_dir_path, saves)
            fresh[system_id] = {'snapshot': version, 'sizes': sizes}
            # Persist as we go. Walking a system's snapshot is the expensive part, and a refresh
            # that dies (or is killed) part way through must not throw away the systems already
            # done — the next run reuses them instead of re-walking every snapshot.
            _save_cache(cache_path, {**cached, **fresh})

        fresh[system_id] = {'snapshot': version, 'sizes': sizes}

        system_catalog = game_service.catalog_releases[system_id]
        for rompath, size_mb in sizes.items():
            game_data = system_catalog.get(rompath)
            if game_data is not None:
                game_data['size_mb'] = size_mb
                sized_count += 1

    _save_cache(cache_path, fresh)
    logger.info(
        f"Release sizes: {sized_count} games sized across {len(fresh)} systems "
        f"({reused_systems} reused from cache, {len(fresh) - reused_systems} recomputed)"
    )
    return sized_count
