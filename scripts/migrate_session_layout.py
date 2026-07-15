"""Migrate the on-disk session layout from ``data/sessions/<sid>/`` to
``data/session/<sid>/`` (singular — spec AD-8 / Phase 4).

Background
----------
The service historically wrote to ``data/sessions/<session_id>/`` (plural).
The spec (AD-8 / Phase 4) and the ME4-UI response-validator Stage 3
require ``data/session/<session_id>/`` (singular).  This script performs
the rename in a safe, atomic-per-session, idempotent, dry-runnable way.

Behaviour
---------
1. **Per-session rename** (atomic via ``os.replace``): for every
   ``<DATA_DIR>/sessions/<sid>/`` directory, move it to
   ``<DATA_DIR>/session/<sid>/``.  If the target already exists, skip
   (idempotency).
2. **Backup-first**: copy ``<DATA_DIR>/sessions/`` to
   ``<DATA_DIR>/sessions.legacy-<ts>/`` before the first move.  Only
   delete the backup after the move succeeds.  In dry-run mode the
   backup is simulated, not created.
3. **Empty pre-1.0.5 leftovers**: rename empty ``work/`` and
   ``work.backup-*`` directories to ``*.legacy-empty-<ts>/`` instead of
   deleting them.  If a non-empty ``work/session/<sid>/`` still holds
   real files, DO NOT touch ``work/`` and emit a warning to the report
   + log (operator decision required).
4. **JSON report** to stdout AND a log file under
   ``<DATA_DIR>/migration/<timestamp>.log``.

Flags
-----
* ``--dry-run`` (default when no ``--force`` is supplied): simulate
  every step; create no files; print the report to stdout.
* ``--force``: actually perform the move.  Without ``--force`` the
  script runs in dry-run mode (safe default).
* ``--data-dir <path>``: override ``settings.data_dir`` (default: from
  ``app.config.settings``).

Exit codes
----------
* 0 = clean (no work needed OR all moves succeeded)
* 1 = partial (some moves failed; see report)
* 2 = needs operator review (non-empty ``work/`` with real data was
        detected and intentionally NOT touched)

Idempotency
-----------
Running this script twice in a row is a no-op the second time:
``<DATA_DIR>/session/<sid>/`` already exists, so the per-session loop
skips.  The ``data/sessions/`` directory may be removed at the end of a
clean run; if so, the second run simply reports "nothing to do".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Projekt-Root zu sys.path, damit ``app.config`` importiert werden kann
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import settings  # noqa: E402
from app.logging_config import get_logger  # noqa: E402

logger = get_logger("migrate_session_layout")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    """UTC timestamp in the form ``YYYYMMDDTHHMMSSZ`` (filesystem-safe)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _safe_listdir(p: Path) -> list[Path]:
    """List ``p`` if it exists and is a directory; else return ``[]``."""
    if not p.exists() or not p.is_dir():
        return []
    return list(p.iterdir())


def _dir_has_real_files(p: Path) -> bool:
    """True if ``p`` contains any file or non-empty subdirectory.

    Used to distinguish "this empty ``work/`` is a pre-1.0.5 leftover we
    can rename" from "this ``work/`` is a real ``work/`` tree we MUST
    NOT touch".  ``.DS_Store`` and similar dotfiles do not count.
    """
    if not p.exists() or not p.is_dir():
        return False
    for entry in p.rglob("*"):
        if entry.is_file() and entry.name != ".DS_Store":
            return True
    return False


# ---------------------------------------------------------------------------
# Core migration logic
# ---------------------------------------------------------------------------


def _backup_legacy_root(
    legacy_root: Path,
    backup_root: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Copy the entire ``legacy_root`` tree to ``backup_root`` (recursive).

    Returns a small status dict for the report.  Uses ``shutil.copytree``
    with ``dirs_exist_ok=True`` so an interrupted previous run that
    left a partial backup is resumed, not blown away.
    """
    if dry_run:
        n_files = sum(1 for _ in legacy_root.rglob("*") if _.is_file())
        return {
            "backup_root": str(backup_root),
            "files_backed_up": n_files,
            "dry_run": True,
        }
    backup_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(legacy_root, backup_root, dirs_exist_ok=True)
    n_files = sum(1 for _ in backup_root.rglob("*") if _.is_file())
    return {
        "backup_root": str(backup_root),
        "files_backed_up": n_files,
        "dry_run": False,
    }


def _move_session(
    legacy_sid_dir: Path,
    canonical_sid_dir: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Atomic per-session rename via ``os.replace``.

    Other processes will observe either fully-old or fully-new — no
    half-state.  We deliberately do NOT recurse into the session dir;
    the whole subtree moves as one unit (one inode rename on POSIX).
    """
    if dry_run:
        n_files = sum(1 for _ in legacy_sid_dir.rglob("*") if _.is_file())
        return {
            "sid": legacy_sid_dir.name,
            "from": str(legacy_sid_dir),
            "to": str(canonical_sid_dir),
            "files_moved": n_files,
            "dry_run": True,
            "ok": True,
        }
    canonical_sid_dir.parent.mkdir(parents=True, exist_ok=True)
    # ``os.replace`` is atomic on POSIX and Windows when source and
    # destination are on the same filesystem (they are: both live under
    # ``settings.data_dir``).
    os.replace(legacy_sid_dir, canonical_sid_dir)
    n_files = sum(1 for _ in canonical_sid_dir.rglob("*") if _.is_file())
    return {
        "sid": canonical_sid_dir.name,
        "from": str(legacy_sid_dir),
        "to": str(canonical_sid_dir),
        "files_moved": n_files,
        "dry_run": False,
        "ok": True,
    }


def _rename_empty_work_leftover(
    work_dir: Path,
    legacy_target: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Rename an empty ``work/`` (or ``work.backup-*``) to ``*.legacy-empty-<ts>``.

    Only safe if the directory is empty (or contains only ``.DS_Store``
    / hidden noise).  A non-empty ``work/`` MUST NOT be touched — the
    caller is expected to check ``_dir_has_real_files`` first and
    surface a warning instead.
    """
    if dry_run:
        return {
            "from": str(work_dir),
            "to": str(legacy_target),
            "dry_run": True,
            "ok": True,
        }
    work_dir.rename(legacy_target)
    return {
        "from": str(work_dir),
        "to": str(legacy_target),
        "dry_run": False,
        "ok": True,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_migration(
    data_dir: str | os.PathLike[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Run the migration.  Returns the report dict (also printed as JSON).

    The report is the single source of truth — it is the value of the
    last ``json.dumps(...)`` line emitted by this function.  The
    lifespan-startup caller (``main.py``) consumes it for the
    "migration complete: moved N sessions in M seconds" log line.
    """
    started_at = time.monotonic()
    started_iso = datetime.now(UTC).isoformat(timespec="seconds")
    dry_run = not force
    ts = _timestamp()

    root = Path(data_dir).resolve()
    legacy_sessions_dir = root / "sessions"
    canonical_sessions_dir = root / "session"
    backup_root = root / f"sessions.legacy-{ts}"
    migration_log_dir = root / "migration"
    migration_log_path = migration_log_dir / f"{ts}.log"

    report: dict[str, Any] = {
        "started_at": started_iso,
        "dry_run": dry_run,
        "data_dir": str(root),
        "ts": ts,
        "sessions": {
            "moved": [],
            "skipped_existing": [],
            "errors": [],
        },
        "work_leftovers": {
            "renamed": [],
            "warnings": [],
        },
        "backup": None,
        "migration_log": None,
        "exit_code": 0,
    }

    # --- 0. Nothing to do? ---
    if not legacy_sessions_dir.exists():
        report["_note"] = (
            f"no legacy layout found at {legacy_sessions_dir}; nothing to do"
        )
    else:
        # --- 1. Backup first ---
        try:
            report["backup"] = _backup_legacy_root(
                legacy_sessions_dir, backup_root, dry_run=dry_run
            )
        except Exception as e:  # noqa: BLE001
            report["backup"] = {"ok": False, "error": str(e)}
            report["exit_code"] = 1
            logger.error("backup failed: %s", e)

        # --- 2. Per-session move ---
        sid_dirs = sorted(
            d for d in _safe_listdir(legacy_sessions_dir) if d.is_dir()
        )
        for legacy_sid_dir in sid_dirs:
            canonical_sid_dir = canonical_sessions_dir / legacy_sid_dir.name
            try:
                if canonical_sid_dir.exists():
                    # Idempotency: target already there, skip.
                    report["sessions"]["skipped_existing"].append(
                        {
                            "sid": legacy_sid_dir.name,
                            "target": str(canonical_sid_dir),
                        }
                    )
                    continue
                rec = _move_session(
                    legacy_sid_dir,
                    canonical_sid_dir,
                    dry_run=dry_run,
                )
                report["sessions"]["moved"].append(rec)
            except Exception as e:  # noqa: BLE001
                report["sessions"]["errors"].append(
                    {
                        "sid": legacy_sid_dir.name,
                        "error": str(e),
                    }
                )
                report["exit_code"] = 1
                logger.error("move %s failed: %s", legacy_sid_dir, e)

        # --- 3. Clean up empty legacy root if everything moved ---
        if not dry_run and legacy_sessions_dir.exists():
            try:
                if not _safe_listdir(legacy_sessions_dir):
                    legacy_sessions_dir.rmdir()
            except OSError:
                # Non-empty (e.g. files at root, not under any <sid>/):
                # leave it for the operator.
                pass

    # --- 4. Pre-1.0.5 leftover cleanup ---
    # ``work/`` (empty) and ``work.backup-*`` (any empty one) get renamed.
    candidates: list[Path] = []
    work_dir = root / "work"
    if work_dir.exists() and work_dir.is_dir():
        candidates.append(work_dir)
    for d in _safe_listdir(root):
        if d.is_dir() and d.name.startswith("work.backup-"):
            candidates.append(d)
    for c in candidates:
        if _dir_has_real_files(c):
            # Non-empty: warning only, do NOT touch.
            msg = (
                f"{c} contains real files; NOT renamed — operator review "
                f"required.  See CHANGELOG.md section 1.1.0 for manual cleanup."
            )
            report["work_leftovers"]["warnings"].append(
                {"path": str(c), "reason": "non-empty"}
            )
            logger.warning(msg)
            # Per task C3 / acceptance F: non-empty work/ with real files
            # bumps the exit code to 2 (operator decision needed).
            if report["exit_code"] == 0:
                report["exit_code"] = 2
            continue
        target = root / f"{c.name}.legacy-empty-{ts}"
        try:
            rec = _rename_empty_work_leftover(c, target, dry_run=dry_run)
            report["work_leftovers"]["renamed"].append(rec)
        except Exception as e:  # noqa: BLE001
            report["work_leftovers"]["warnings"].append(
                {"path": str(c), "error": str(e)}
            )
            if report["exit_code"] == 0:
                report["exit_code"] = 1
            logger.error("rename leftover %s failed: %s", c, e)

    # --- 5. Persist report ---
    if not dry_run:
        migration_log_dir.mkdir(parents=True, exist_ok=True)
        migration_log_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report["migration_log"] = str(migration_log_path)

    report["duration_sec"] = round(time.monotonic() - started_at, 3)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate data/sessions/<sid>/ to data/session/<sid>/.  "
            "Default mode is --dry-run; pass --force to actually move."
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=settings.data_dir,
        help="Path to DATA_DIR (default: settings.data_dir)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually perform the move (default: dry-run).",
    )
    args = parser.parse_args()
    report = run_migration(args.data_dir, force=args.force)
    # Single-line JSON to stdout (machine-parseable) AND a human summary
    # line for the operator.  Always exit with the reported code.
    print(json.dumps(report, indent=2, ensure_ascii=False))
    n_moved = len(report["sessions"]["moved"])
    n_skipped = len(report["sessions"]["skipped_existing"])
    n_errors = len(report["sessions"]["errors"])
    n_renamed = len(report["work_leftovers"]["renamed"])
    n_warn = len(report["work_leftovers"]["warnings"])
    if report["dry_run"]:
        print(
            f"[dry-run] would move {n_moved} session(s), skip {n_skipped}, "
            f"rename {n_renamed} leftover(s); errors={n_errors} "
            f"warnings={n_warn}.  Pass --force to execute.",
            file=sys.stderr,
        )
    else:
        logger.info(
            "migration complete: moved %d session(s) in %ss; "
            "skipped %d, errors %d, leftovers renamed %d, warnings %d",
            n_moved,
            report["duration_sec"],
            n_skipped,
            n_errors,
            n_renamed,
            n_warn,
        )
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
