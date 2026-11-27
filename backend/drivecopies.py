"""Find a copy of a file that another PC already put on the backup drive.

Several PCs can back up to the same drive. Each PC has its own folder there (marked by a pc-id.json), so the same
document would be stored once per PC. Before a PC writes a file, it asks this catalog whether a copy with the same
content (SHA-256) already exists in another PC's folder. If so, the app links to it instead of writing it again.

Only the folders of other PCs are read. Nothing here ever writes to, moves or deletes a file on the drive.
"""
from __future__ import annotations

import hashlib
import gzip
import os
import struct
from pathlib import Path

SKIP_NAMES = {"pc-id.json", "choices.json.gz", "organized-index.json", "desktop.ini", "thumbs.db"}
MAX_TRIES = 8                       # content checks per file: same-named files are tried first
MIN_SIZE = 1                        # an empty file has no content worth sharing


def other_pc_folders(dest, own: str, include_own: bool = False) -> list[str]:
    """Folders on `dest` that belong to another PC (they hold a pc-id.json). `include_own` adds this PC's own folder, for
    when other PCs have also written into it (they back this PC up over the network): its files are then not all ours."""
    out = []
    try:
        entries = list(os.scandir(dest))
    except OSError:
        return out
    for e in entries:
        if (e.name == own and not include_own) or e.name.startswith("."):
            continue
        try:
            if e.is_dir(follow_symlinks=False) and os.path.isfile(os.path.join(e.path, "pc-id.json")):
                out.append(e.path)
        except OSError:
            pass
    return out


def _gz_size(path: str) -> int | None:
    """Size of the file inside a .gz, from its last four bytes (it is exact below 4 GB)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(-4, os.SEEK_END)
            return struct.unpack("<I", fh.read(4))[0]
    except (OSError, struct.error):
        return None


def _hash(path: str, gz: bool) -> str | None:
    sha = hashlib.sha256()
    try:
        with (gzip.open(path, "rb") if gz else open(path, "rb")) as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                sha.update(chunk)
    except (OSError, EOFError):
        return None                  # a damaged or unreadable copy is simply not a candidate
    return sha.hexdigest()


class Catalog:
    """What the other PCs stored on one drive, looked up by size first and content second. Built on first use."""

    def __init__(self, dest, own: str, cancel=None, include_own: bool = False):
        self.dest, self.own, self.cancel = str(dest), own, cancel
        self.folders = other_pc_folders(dest, own, include_own)
        self._by_size: dict[bool, dict[int, list[str]]] = {}
        self._hashes: dict[tuple[str, bool], str | None] = {}

    @property
    def usable(self) -> bool:
        return bool(self.folders)

    def _build(self, gz: bool) -> dict[int, list[str]]:
        found: dict[int, list[str]] = {}
        stack = list(self.folders)
        while stack:
            if self.cancel:
                self.cancel()
            try:
                it = os.scandir(stack.pop())
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name != ".versions":
                                stack.append(e.path)
                            continue
                        if not e.is_file(follow_symlinks=False):
                            continue
                        name = e.name.lower()
                        if name in SKIP_NAMES or name.endswith(".part") or name.endswith(".gz") != gz:
                            continue
                        size = _gz_size(e.path) if gz else e.stat().st_size
                    except OSError:
                        continue
                    if size is not None and size >= MIN_SIZE:
                        found.setdefault(size, []).append(e.path)
        return found

    def _build_known(self) -> set:
        """Every file the other PCs stored, as (name, size, whole-second date, compressed): no file is opened except .gz tails."""
        known = set()
        stack = list(self.folders)
        while stack:
            if self.cancel:
                self.cancel()
            try:
                it = os.scandir(stack.pop())
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name != ".versions":
                                stack.append(e.path)
                            continue
                        name = e.name.lower()
                        if name in SKIP_NAMES or name.endswith(".part") or not e.is_file(follow_symlinks=False):
                            continue
                        st = e.stat()
                        gz = name.endswith(".gz")
                        size = _gz_size(e.path) if gz else st.st_size
                    except OSError:
                        continue
                    if size is not None and size >= MIN_SIZE:
                        known.add((name[:-3] if gz else name, size, int(st.st_mtime), gz))
        return known

    def seen(self, name: str, size: int, mtime: float) -> bool:
        """True when another PC stored a file with this name, size and modified time (a quick look, no content is read).
        It only suggests that a copy exists; the backup itself confirms the content before it reuses anything."""
        if not self.usable or size < MIN_SIZE:
            return False
        if not hasattr(self, "_known"):
            self._known = self._build_known()
        n, t = name.lower(), int(mtime)
        return any((n, s, t + d, gz) in self._known for d in range(-2, 3) for s, gz in ((size, False), (size & 0xFFFFFFFF, True)))

    def find(self, digest: str, size: int, name: str, gz: bool):
        """A path on the drive, in another PC's folder, whose content is exactly `digest`; None if there is none."""
        if not self.usable or size < MIN_SIZE:
            return None
        if gz not in self._by_size:
            self._by_size[gz] = self._build(gz)
        cands = self._by_size[gz].get(size & 0xFFFFFFFF if gz else size, [])
        base = name.lower()
        cands = sorted(cands, key=lambda p: Path(p).name.lower().removesuffix(".gz") != base)
        for p in cands[:MAX_TRIES]:
            key = (p, gz)
            if key not in self._hashes:
                self._hashes[key] = _hash(p, gz)
            if self._hashes[key] == digest and os.path.isfile(p):
                return p
        return None
