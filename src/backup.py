"""
Backup helper.

Before modifying any drawing, call backup_file() to copy it to a
timestamped subfolder under backups/.

Usage:
    from src.backup import backup_file
    backup_path = backup_file(Path("E:/RC-Projects/drawing_001.dwg"))
"""

import shutil
from datetime import datetime
from pathlib import Path


# Where backups go. Sits next to the project's source code.
BACKUP_ROOT = Path(__file__).parent.parent / "backups"


def backup_file(source_path: Path) -> Path:
    """
    Copy `source_path` into a timestamped backup folder.

    Returns the full path to the backup file.
    Raises FileNotFoundError if source does not exist.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = BACKUP_ROOT / timestamp
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / source_path.name
    shutil.copy2(source_path, target_path)
    return target_path