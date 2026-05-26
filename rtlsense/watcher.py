"""File watcher: detect changed modules and trigger re-analysis."""

import hashlib
import logging
import shelve
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from .synthesizer import extract_modules_from_file

logger = logging.getLogger(__name__)


def _file_hash(path: str) -> str:
    try:
        return hashlib.md5(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


class _ChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        on_change: Callable[[str, list[str]], None],
        cache_dir: str,
        extensions: tuple[str, ...] = (".v", ".sv"),
    ):
        self._on_change = on_change
        self._extensions = extensions
        self._hash_cache: dict[str, str] = {}
        self._debounce_seen: dict[str, float] = {}
        self._debounce_delay = 0.5  # seconds

        # Load persisted hashes so we don't re-analyse on startup
        cache_path = Path(cache_dir) / "file_hashes"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with shelve.open(str(cache_path)) as db:
            self._hash_cache = dict(db)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = str(event.src_path)
        if not any(path.endswith(ext) for ext in self._extensions):
            return

        # Debounce: editors often fire multiple events per save
        now = time.time()
        if now - self._debounce_seen.get(path, 0) < self._debounce_delay:
            return
        self._debounce_seen[path] = now

        new_hash = _file_hash(path)
        if new_hash == self._hash_cache.get(path):
            return  # Content unchanged (e.g., editor touch on save)
        self._hash_cache[path] = new_hash

        modules = extract_modules_from_file(path)
        if not modules:
            logger.debug("No modules found in %s, skipping.", path)
            return

        logger.info("Change detected in %s, modules: %s", path, modules)
        self._on_change(path, modules)


def watch_directory(
    directory: str,
    on_change: Callable[[str, list[str]], None],
    cache_dir: str,
) -> None:
    """
    Block and watch a directory for Verilog file changes.
    Calls on_change(filepath, [module_names]) on each meaningful save.
    """
    handler = _ChangeHandler(on_change=on_change, cache_dir=cache_dir)
    observer = Observer()
    observer.schedule(handler, directory, recursive=True)
    observer.start()

    from rich.console import Console
    Console().print(
        f"[dim]Watching [bold]{directory}[/bold] for changes... (Ctrl+C to stop)[/dim]"
    )

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
