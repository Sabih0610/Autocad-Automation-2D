import hashlib
from pathlib import Path

import pytest

from src import backup


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_backup_file_verifies_and_preserves_exact_bytes(tmp_path, monkeypatch) -> None:
    source = tmp_path / "drawing.dwg"
    source.write_bytes(b"original drawing bytes\x00\xff")
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")

    backup_path = backup.backup_file(source)

    assert backup_path.is_file()
    assert _sha256(backup_path) == _sha256(source)


def test_backup_file_rejects_a_corrupt_copy(tmp_path, monkeypatch) -> None:
    source = tmp_path / "drawing.dwg"
    source.write_bytes(b"original drawing bytes")
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")

    def corrupt_copy(_source, target):
        Path(target).write_bytes(b"corrupt")

    monkeypatch.setattr(backup.shutil, "copy2", corrupt_copy)

    with pytest.raises(OSError, match="Backup integrity check failed"):
        backup.backup_file(source)


def test_restore_file_replaces_target_with_backup_bytes(tmp_path) -> None:
    backup_path = tmp_path / "drawing.backup.dwg"
    target_path = tmp_path / "drawing.dwg"
    backup_path.write_bytes(b"known good drawing")
    target_path.write_bytes(b"damaged drawing")

    restored_path = backup.restore_file(backup_path, target_path)

    assert restored_path == target_path
    assert target_path.read_bytes() == b"known good drawing"
