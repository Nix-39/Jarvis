"""
BackupService - encrypted nightly backup of data/ to another disk.

What is backed up: everything in data/ (memory database, calendar, lessons,
settings, photos, documents ...) except the vector index (data/vector_store is
derived data and is rebuilt from SQLite and the documents) and temporary files.
SQLite databases are copied with SQLite's own backup API, so a backup taken
while Jarvis is running is still consistent.

Encryption: the archive (tar.gz) is streamed through AES-256-GCM in 1 MiB
chunks - nothing unencrypted is ever written to disk. The key is derived from
BACKUP_PASSPHRASE with scrypt and a random salt per backup. Every chunk is
authenticated, the last one is marked final, and the header is bound to every
chunk, so a wrong passphrase, a modified file or a truncated file is detected.

    File format (.ygg):
        "YGGBAK1\\n" | salt (16) | scrypt log2(N), r, p (3) | nonce prefix (7)
        then chunks: length (4, big endian) | AES-GCM ciphertext+tag
        nonce = prefix (7) | chunk counter (4) | final flag (1)

Each backup is verified (decrypted and read through) before it gets its final
name; the newest BACKUP_KEEP backups are kept.

CLI (restoring never touches the live data/ folder):
    python -m services.backup_service status
    python -m services.backup_service run
    python -m services.backup_service verify  <file.ygg>
    python -m services.backup_service restore <file.ygg> <empty target folder>
"""

from __future__ import annotations

import getpass
import hashlib
import io
import os
import re
import sqlite3
import sys
import tarfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

MAGIC = b"YGGBAK1\n"
SALT_BYTES, PREFIX_BYTES = 16, 7
HEADER_BYTES = len(MAGIC) + SALT_BYTES + 3 + PREFIX_BYTES
CHUNK_BYTES = 1 << 20
SCRYPT_N_LOG2, SCRYPT_R, SCRYPT_P = 16, 8, 1          # ~64 MB memory, a fraction of a second
MIN_PASSPHRASE = 12
NAME_RE = re.compile(r"^yggdrasil-(\d{8}-\d{6})\.ygg$")
EXCLUDED_DIRS = {"vector_store"}
EXCLUDED_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".part")
RETRY_AFTER_FAILURE = timedelta(hours=1)
NOTIFY_INTERVAL = timedelta(hours=12)


class BackupError(Exception):
    pass


# ----------------------------------------------------------------------
# Encryption
# ----------------------------------------------------------------------

def _aead(passphrase: str, salt: bytes, n_log2: int, r: int, p: int):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:   # pragma: no cover - depends on the installation
        raise BackupError("Paketet 'cryptography' saknas: kör  pip install cryptography") from exc
    if not 14 <= n_log2 <= 20 or not 1 <= r <= 16 or not 1 <= p <= 4:
        raise BackupError("Okända krypteringsparametrar i filen.")
    key = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=1 << n_log2, r=r, p=p,
                         maxmem=256 * 1024 * 1024, dklen=32)
    return AESGCM(key)


def _nonce(prefix: bytes, counter: int, final: bool) -> bytes:
    return prefix + counter.to_bytes(4, "big") + (b"\x01" if final else b"\x00")


class EncryptingWriter(io.RawIOBase):
    """Write-only stream: plaintext in, encrypted chunks out."""

    def __init__(self, out: io.BufferedIOBase, passphrase: str) -> None:
        super().__init__()
        salt, self._prefix = os.urandom(SALT_BYTES), os.urandom(PREFIX_BYTES)
        self._header = MAGIC + salt + bytes([SCRYPT_N_LOG2, SCRYPT_R, SCRYPT_P]) + self._prefix
        self._aead = _aead(passphrase, salt, SCRYPT_N_LOG2, SCRYPT_R, SCRYPT_P)
        self._out, self._buf, self._counter, self._finished = out, bytearray(), 0, False
        out.write(self._header)

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        if self._finished:
            raise ValueError("write after finish")
        self._buf += data
        while len(self._buf) >= CHUNK_BYTES:
            self._emit(bytes(self._buf[:CHUNK_BYTES]), final=False)
            del self._buf[:CHUNK_BYTES]
        return len(data)

    def finish(self) -> None:
        if not self._finished:
            self._emit(bytes(self._buf), final=True)
            self._buf.clear()
            self._finished = True

    def _emit(self, chunk: bytes, final: bool) -> None:
        if self._counter >= 2 ** 32:
            raise BackupError("Backupen är för stor.")
        sealed = self._aead.encrypt(_nonce(self._prefix, self._counter, final), chunk, self._header)
        self._out.write(len(sealed).to_bytes(4, "big"))
        self._out.write(sealed)
        self._counter += 1


def decrypt_chunks(src: io.BufferedIOBase, passphrase: str) -> Iterator[bytes]:
    """Yield the plaintext of an encrypted backup, chunk by chunk. Raises BackupError on any problem."""
    from cryptography.exceptions import InvalidTag

    header = src.read(HEADER_BYTES)
    if len(header) < HEADER_BYTES or not header.startswith(MAGIC):
        raise BackupError("Filen är ingen Yggdrasil-backup.")
    salt = header[len(MAGIC):len(MAGIC) + SALT_BYTES]
    n_log2, r, p = header[len(MAGIC) + SALT_BYTES:len(MAGIC) + SALT_BYTES + 3]
    prefix = header[-PREFIX_BYTES:]
    aead = _aead(passphrase, salt, n_log2, r, p)
    counter = 0
    while True:
        size_bytes = src.read(4)
        if len(size_bytes) < 4:
            raise BackupError("Filen är avkortad (slutet saknas).")
        size = int.from_bytes(size_bytes, "big")
        if not 16 <= size <= CHUNK_BYTES + 16:
            raise BackupError("Filen är skadad.")
        sealed = src.read(size)
        if len(sealed) < size:
            raise BackupError("Filen är avkortad (slutet saknas).")
        for final in (False, True):
            try:
                plain = aead.decrypt(_nonce(prefix, counter, final), sealed, header)
                break
            except InvalidTag:
                continue
        else:
            raise BackupError("Fel lösenfras, eller så har filen ändrats." if counter == 0 else "Filen är skadad eller ändrad.")
        counter += 1
        yield plain
        if final:
            if src.read(1):
                raise BackupError("Filen har extra data efter slutet.")
            return


class DecryptingReader(io.RawIOBase):
    """Read-only stream over decrypt_chunks (for tarfile)."""

    def __init__(self, src: io.BufferedIOBase, passphrase: str) -> None:
        super().__init__()
        self._chunks, self._buf = decrypt_chunks(src, passphrase), b""

    def readable(self) -> bool:
        return True

    def readinto(self, target: Any) -> int:
        while not self._buf:
            try:
                self._buf = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(target), len(self._buf))
        target[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class BackupResult:
    path: Path
    files: int
    bytes: int
    seconds: float
    skipped: tuple[str, ...]


class BackupService:
    def __init__(
        self,
        backup_dir: str = Config.BACKUP_DIR,
        passphrase: str = Config.BACKUP_PASSPHRASE,
        data_dir: Path = Config.DATA_DIR,
        keep: int = Config.BACKUP_KEEP,
        at: str = Config.BACKUP_TIME,
        notify: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self._passphrase = passphrase
        self.data_dir = Path(data_dir)
        self.keep = max(1, keep)
        self.at = at if re.fullmatch(r"\d{2}:\d{2}", at or "") else "03:00"
        self.notify = notify
        self._lock = threading.Lock()
        self.running = False
        self.last_error: Optional[str] = None
        self._last_failure: Optional[datetime] = None
        self._last_notified: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Configuration checks
    # ------------------------------------------------------------------

    def problem(self) -> Optional[str]:
        """Why backups cannot run, in Swedish - or None when everything is set up."""
        if self.backup_dir is None:
            return "Backup är avstängd (BACKUP_DIR är tom i .env)."
        if len(self._passphrase) < MIN_PASSPHRASE:
            return f"BACKUP_PASSPHRASE i .env saknas eller är kortare än {MIN_PASSPHRASE} tecken."
        try:
            target = self.backup_dir.resolve()
            if target == self.data_dir.resolve() or self.data_dir.resolve() in target.parents:
                return "BACKUP_DIR får inte ligga inuti data-mappen."
        except OSError:
            pass
        anchor = Path(self.backup_dir.anchor or ".")
        if not anchor.exists():
            return f"Backupdisken {self.backup_dir.anchor} hittas inte."
        return None

    @property
    def enabled(self) -> bool:
        return self.problem() is None

    @property
    def configured(self) -> bool:
        """Backups are switched on in .env (the disk may still be missing)."""
        return self.backup_dir is not None and len(self._passphrase) >= MIN_PASSPHRASE

    def same_disk(self) -> bool:
        return bool(self.backup_dir and self.backup_dir.drive and self.backup_dir.drive.lower() == self.data_dir.resolve().drive.lower())

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def run(self, reason: str = "manual") -> BackupResult:
        """Create, verify and keep one encrypted backup. Raises BackupError."""
        if not self._lock.acquire(blocking=False):
            raise BackupError("En backup körs redan.")
        self.running = True
        started = time.monotonic()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        part = final = None
        try:
            problem = self.problem()   # e.g. the backup disk is gone: report it like any failure
            if problem:
                raise BackupError(problem)
            event_bus.publish("backup.started", "backup", "Backup startar…", reason=reason)
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            final = self.backup_dir / f"yggdrasil-{stamp}.ygg"
            part = final.with_suffix(".ygg.part")
            with open(part, "wb") as raw:
                writer = EncryptingWriter(raw, self._passphrase)
                with tarfile.open(fileobj=writer, mode="w|gz", format=tarfile.PAX_FORMAT) as tar:
                    files, skipped = self._add_data(tar)
                writer.finish()
                raw.flush()
                os.fsync(raw.fileno())
            checked = self.verify(part)
            if checked != files:
                raise BackupError(f"Kontrollen hittade {checked} filer, väntade {files}.")
            part.replace(final)
            self._prune()
            result = BackupResult(final, files, final.stat().st_size, time.monotonic() - started, tuple(skipped))
        except Exception as exc:
            if part is not None:
                part.unlink(missing_ok=True)
            self.last_error = str(exc) if isinstance(exc, BackupError) else f"{type(exc).__name__}: {exc}"
            self._last_failure = datetime.now()
            logger.error("Backup failed: %s", self.last_error)
            event_bus.publish("backup.failed", "backup", f"Backup misslyckades: {self.last_error}")
            self._notify_failure()
            raise BackupError(self.last_error) from exc
        finally:
            self.running = False
            self._lock.release()

        self.last_error = None
        logger.info("Backup %s written (%d files, %s, %.1f s).", result.path.name, result.files, _size(result.bytes), result.seconds)
        note = f" ({len(result.skipped)} filer kunde inte läsas)" if result.skipped else ""
        event_bus.publish("backup.completed", "backup", f"Backup klar: {result.files} filer, {_size(result.bytes)}{note}",
                          files=result.files, bytes=result.bytes)
        return result

    def _add_data(self, tar: tarfile.TarFile) -> tuple[int, list[str]]:
        count, skipped = 0, []
        for path in sorted(self.data_dir.rglob("*")):
            rel = path.relative_to(self.data_dir)
            if rel.parts[0] in EXCLUDED_DIRS or path.is_symlink() or path.name.endswith(EXCLUDED_SUFFIXES):
                continue
            arcname = "data/" + rel.as_posix()
            try:
                if path.is_dir():
                    tar.add(path, arcname=arcname, recursive=False)
                elif path.suffix == ".db":
                    data = _sqlite_snapshot(path)
                    info = tar.gettarinfo(path, arcname=arcname)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                elif path.is_file():
                    tar.add(path, arcname=arcname, recursive=False)
                else:
                    continue
                count += 1
            except (OSError, sqlite3.Error) as exc:
                logger.warning("Backup skipped %s: %s", rel, exc)
                skipped.append(str(rel))
        return count, skipped

    def verify(self, path: Path) -> int:
        """Decrypt and read the whole backup. Returns the number of entries; raises BackupError."""
        try:
            with open(path, "rb") as raw, tarfile.open(fileobj=DecryptingReader(raw, self._passphrase), mode="r|gz") as tar:
                count = 0
                for member in tar:
                    if member.isfile():
                        handle = tar.extractfile(member)
                        while handle and handle.read(CHUNK_BYTES):
                            pass
                    count += 1
                return count
        except BackupError:
            raise
        except (tarfile.TarError, OSError, EOFError) as exc:
            raise BackupError(f"Backupen kunde inte läsas: {exc}") from exc

    def restore(self, path: Path, target: Path) -> int:
        """Unpack a backup into an empty folder (never into the live data folder)."""
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise BackupError("Målmappen måste vara tom eller inte finnas.")
        if target.resolve() == self.data_dir.resolve():
            raise BackupError("Packa upp till en ny mapp, inte direkt i data-mappen.")
        self.verify(path)   # check everything before writing a single file
        target.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(path, "rb") as raw, tarfile.open(fileobj=DecryptingReader(raw, self._passphrase), mode="r|gz") as tar:
            for member in tar:
                tar.extract(member, target, filter="data")   # no absolute paths, '..' or links outside
                count += 1
        return count

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------

    def backups(self) -> list[tuple[datetime, Path]]:
        if self.backup_dir is None or not self.backup_dir.is_dir():
            return []
        found = []
        for path in self.backup_dir.iterdir():
            match = NAME_RE.match(path.name)
            if match:
                found.append((datetime.strptime(match.group(1), "%Y%m%d-%H%M%S"), path))
        return sorted(found)

    def next_run(self, now: Optional[datetime] = None) -> Optional[datetime]:
        if not self.configured:
            return None
        now = now or datetime.now()
        hour, minute = map(int, self.at.split(":"))
        slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)   # today's backup time
        backups = self.backups()
        latest = backups[-1][0] if backups else None
        if latest is None:
            due = now                                    # never backed up: do it right away
        elif now >= slot:
            due = slot if latest < slot else slot + timedelta(days=1)
        else:
            due = now if latest < slot - timedelta(days=1) else slot   # last night was missed (PC off)
        if self._last_failure and due < self._last_failure + RETRY_AFTER_FAILURE:
            due = self._last_failure + RETRY_AFTER_FAILURE
        return due

    def run_forever(self, stop: threading.Event) -> None:
        """Thread in Jarvis Core: backup at BACKUP_TIME, or as soon as possible after a missed night."""
        if stop.wait(120):   # let the core start up first
            return
        while not stop.is_set():
            try:
                due = self.next_run()
                if due is not None and datetime.now() >= due and not self.running:
                    self.run("schedule")
            except BackupError:
                pass   # already logged, published and notified
            except Exception as exc:   # never let the thread die
                logger.exception("Backup scheduler error: %s", exc)
            stop.wait(60)

    def status(self) -> dict[str, Any]:
        backups = self.backups()
        latest = backups[-1] if backups else None
        nxt = self.next_run()
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "problem": self.problem(),
            "dir": str(self.backup_dir) if self.backup_dir else "",
            "same_disk": self.same_disk(),
            "running": self.running,
            "last_backup": latest[0].isoformat(timespec="minutes") if latest else None,
            "last_size": latest[1].stat().st_size if latest else None,
            "count": len(backups),
            "total_size": sum(p.stat().st_size for _, p in backups),
            "last_error": self.last_error,
            "next_run": nxt.isoformat(timespec="minutes") if nxt else None,
            "time": self.at,
            "keep": self.keep,
        }

    # ------------------------------------------------------------------

    def _prune(self) -> None:
        backups = self.backups()
        for _, path in backups[:-self.keep]:
            try:
                path.unlink()
                logger.info("Old backup %s removed.", path.name)
            except OSError as exc:
                logger.warning("Could not remove old backup %s: %s", path.name, exc)
        for stale in self.backup_dir.glob("*.ygg.part"):
            if datetime.now() - datetime.fromtimestamp(stale.stat().st_mtime) > timedelta(hours=6):
                stale.unlink(missing_ok=True)

    def _notify_failure(self) -> None:
        if self.notify is None:
            return
        now = datetime.now()
        if self._last_notified and now - self._last_notified < NOTIFY_INTERVAL:
            return
        self._last_notified = now
        try:
            self.notify("⚠️ Yggdrasil: backupen misslyckades", self.last_error or "Okänt fel")
        except Exception as exc:
            logger.warning("Could not send backup notification: %s", exc)


def _sqlite_snapshot(path: Path) -> bytes:
    """Consistent copy of a (possibly live, WAL-mode) SQLite database."""
    source = sqlite3.connect(path, timeout=10)
    copy = sqlite3.connect(":memory:")
    try:
        source.backup(copy)
        return copy.serialize()
    finally:
        copy.close()
        source.close()


def _size(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    usage = __doc__.split("CLI", 1)[1]
    if not argv or argv[0] not in ("status", "run", "verify", "restore"):
        print("Användning:" + usage.split(":", 1)[1])
        return 2
    command = argv[0]
    passphrase = Config.BACKUP_PASSPHRASE
    if command in ("verify", "restore") and (len(passphrase) < MIN_PASSPHRASE or "--ask" in argv):
        passphrase = getpass.getpass("Lösenfras för backupen: ")
    service = BackupService(passphrase=passphrase)
    args = [a for a in argv[1:] if a != "--ask"]
    try:
        if command == "status":
            for key, value in service.status().items():
                print(f"{key:12} {value}")
        elif command == "run":
            result = service.run("cli")
            print(f"Klar: {result.path} ({result.files} filer, {_size(result.bytes)}, {result.seconds:.1f} s)")
            for name in result.skipped:
                print(f"  kunde inte läsas: {name}")
        elif command == "verify":
            print(f"OK: {service.verify(Path(args[0]))} filer och mappar, lösenfrasen stämmer och inget är ändrat.")
        else:
            count = service.restore(Path(args[0]), Path(args[1]))
            print(f"Uppackat: {count} filer och mappar till {args[1]}")
            print("Stäng av Jarvis Core (scripts\\restart_core.ps1 -Stop), byt ut data-mappen mot den uppackade och starta igen.")
    except (BackupError, IndexError) as exc:
        print(f"Fel: {exc if isinstance(exc, BackupError) else 'saknar argument'}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
