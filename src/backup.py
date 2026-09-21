"""
Backup helper.

Before modifying any drawing, call backup_file() to copy it to a
timestamped subfolder under backups/.

Usage:
    from src.backup import backup_file
    backup_path = backup_file(Path("E:/RC-Projects/drawing_001.dwg"))
"""

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4


# Where backups go. Sits next to the project's source code.
BACKUP_ROOT = Path(__file__).parent.parent / "backups"


def _file_hash(path: Path) -> str:
    """Return a SHA-256 digest for an on-disk file."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup_file(source_path: Path) -> Path:
    """
    Copy `source_path` into a timestamped backup folder.

    Returns the full path to the backup file.
    Raises FileNotFoundError if source does not exist.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f") + "_" + uuid4().hex
    target_dir = BACKUP_ROOT / timestamp
    target_dir.mkdir(parents=True, exist_ok=True)

    source_hash = _file_hash(source_path)
    target_path = target_dir / source_path.name
    shutil.copy2(source_path, target_path)

    # A backup is only useful if it is byte-for-byte identical to the source.
    # This mirrors the integrity check used by the durable changeset workflow.
    if _file_hash(target_path) != source_hash:
        raise OSError(f"Backup integrity check failed for: {source_path}")

    return target_path


def restore_file(backup_path: Path, target_path: Path) -> Path:
    """Restore `backup_path` over `target_path` and return the target path."""
    backup_path = Path(backup_path)
    target_path = Path(target_path)
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {backup_path}")

    shutil.copy2(backup_path, target_path)
    return target_path
