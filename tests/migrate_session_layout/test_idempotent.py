"""Idempotenz + Dry-Run + Work-Leftover-Schutz fuer die Session-Layout-Migration.

Diese Tests verriegeln die drei wichtigsten Operator-Garantien der
Migration (siehe ``scripts/migrate_session_layout.py``):

  1. **Idempotenz**: zwei aufeinanderfolgende Runs machen beim
     zweiten Mal keine Arbeit mehr (alle Sessions sind schon
     verschoben).
  2. **Dry-Run**: ein ``run_migration(force=False)`` darf das
     Dateisystem nicht veraendern.
  3. **Work-Leftover-Schutz**: ein nicht-leeres ``data/work/`` wird
     NICHT angefasst; das Script meldet eine Warnung und der
     Exit-Code steigt auf 2 (operator review).

Test-Strategie:
  * Wir importieren die Python-API ``run_migration`` direkt und geben
    fuer jeden Test ein eigenes ``tmp_path`` als ``data_dir`` mit.
    Dadurch testen wir die selbe Logik, die auch der CLI-Entry-Point
    ``python scripts/migrate_session_layout.py`` aufruft, ohne dass
    wir einen Subprocess starten muessten.
"""
from __future__ import annotations

from pathlib import Path

from scripts.migrate_session_layout import run_migration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_legacy_session(root: Path, sid: str) -> Path:
    """Erzeuge ``<root>/sessions/<sid>/Notes.md + results/<sid>.01result.json``."""
    legacy = root / "sessions" / sid
    (legacy / "results").mkdir(parents=True)
    (legacy / "Notes.md").write_text("# Session " + sid + "\n", encoding="utf-8")
    (legacy / "results" / f"{sid}.01result.json").write_text("{}", encoding="utf-8")
    return legacy


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotent:
    """Migration laeuft beim zweiten Mal als No-Op."""

    def test_second_run_is_a_noop(self, tmp_path: Path):
        _make_legacy_session(tmp_path, "sid-1")
        _make_legacy_session(tmp_path, "sid-2")

        first = run_migration(tmp_path, force=True)
        assert first["exit_code"] == 0
        assert len(first["sessions"]["moved"]) == 2

        # Zweiter Lauf: nichts mehr zu tun
        second = run_migration(tmp_path, force=True)
        assert second["exit_code"] == 0
        assert second["sessions"]["moved"] == []
        # Beide SIDs liegen jetzt in canonical
        for sid in ("sid-1", "sid-2"):
            assert (tmp_path / "session" / sid).exists()
            # Originaldatei ist mit umgezogen
            assert (tmp_path / "session" / sid / "Notes.md").exists()
            assert (tmp_path / "session" / sid / "results" / f"{sid}.01result.json").exists()

    def test_skip_when_target_already_exists(
        self, tmp_path: Path
    ):
        """Wenn canonical schon da ist, wird uebersprungen, nicht
        ueberschrieben."""
        # Pre-existing canonical session (z.B. ein neuer Schreibvorgang
        # waere hier zwischendurch gelandet).
        canonical = tmp_path / "session" / "sid-x"
        canonical.mkdir(parents=True)
        (canonical / "marker.txt").write_text("do-not-touch", encoding="utf-8")
        # Legacy parallel anlegen
        _make_legacy_session(tmp_path, "sid-x")

        report = run_migration(tmp_path, force=True)
        assert (tmp_path / "session" / "sid-x" / "marker.txt").read_text() == "do-not-touch"
        # sid-x landet in skipped_existing, nicht in moved
        skipped = report["sessions"]["skipped_existing"]
        assert any(s["sid"] == "sid-x" for s in skipped), (
            f"sid-x fehlt in skipped_existing: {skipped}"
        )
        assert not any(
            m["sid"] == "sid-x" for m in report["sessions"]["moved"]
        ), "sid-x wurde trotz existentem canonical 'moved' — Datenverlust!"


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    """Dry-Run darf das Dateisystem nicht veraendern."""

    def test_dry_run_does_not_move_files(self, tmp_path: Path):
        _make_legacy_session(tmp_path, "sid-dry-1")
        _make_legacy_session(tmp_path, "sid-dry-2")

        snapshot_before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
        report = run_migration(tmp_path, force=False)
        snapshot_after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

        # 1) Report kennzeichnet sich als dry_run
        assert report["dry_run"] is True
        # 2) Plan in der "moved"-Liste, aber NICHTS auf der Platte
        assert len(report["sessions"]["moved"]) == 2
        for rec in report["sessions"]["moved"]:
            assert rec["dry_run"] is True
        # 3) Original-Tree unveraendert
        assert snapshot_before == snapshot_after, (
            "Dry-Run hat das Dateisystem veraendert — das ist ein Bug!"
        )
        # 4) Kein Migration-Log-File geschrieben
        migration_log_dir = tmp_path / "migration"
        if migration_log_dir.exists():
            assert not any(migration_log_dir.iterdir()), (
                "Dry-Run hat einen Migration-Log geschrieben"
            )
        # 5) Legacy-Tree existiert weiterhin
        assert (tmp_path / "sessions" / "sid-dry-1").exists()
        assert (tmp_path / "sessions" / "sid-dry-2").exists()
        # 6) Canonical NICHT angelegt
        assert not (tmp_path / "session" / "sid-dry-1").exists()
        assert not (tmp_path / "session" / "sid-dry-2").exists()


# ---------------------------------------------------------------------------
# Work leftovers
# ---------------------------------------------------------------------------


class TestWorkLeftovers:
    """Verhalten bei pre-1.0.5 ``work/``- und ``work.backup-*``-Leftovers."""

    def test_non_empty_work_dir_is_untouched_and_warns(self, tmp_path: Path):
        # Real data in work/ — must NOT be renamed
        work_dir = tmp_path / "work"
        (work_dir / "session" / "real-sid").mkdir(parents=True)
        (work_dir / "session" / "real-sid" / "real.json").write_text("{}", encoding="utf-8")
        # And a legacy session to migrate (so the run actually does work)
        _make_legacy_session(tmp_path, "sid-mix-1")

        report = run_migration(tmp_path, force=True)

        # 1) Real files are still there, untouched
        assert (work_dir / "session" / "real-sid" / "real.json").exists()
        assert (work_dir / "session" / "real-sid" / "real.json").read_text() == "{}"
        # 2) work/ was NOT renamed
        assert work_dir.exists(), "work/ wurde umbenannt — Datenverlust!"
        # 3) Warning emitted
        warnings = report["work_leftovers"]["warnings"]
        assert any(w.get("path", "").endswith("/work") for w in warnings), (
            f"Keine Warnung fuer non-empty work/: {warnings}"
        )
        # 4) Exit code = 2 (operator review)
        assert report["exit_code"] == 2, (
            f"Bei non-empty work/ MUSS exit_code=2 sein, "
            f"bekam {report['exit_code']}"
        )

    def test_empty_work_backup_is_renamed(self, tmp_path: Path):
        # Empty work.backup-2026-07-13/ — should be renamed to legacy-empty-*
        wb = tmp_path / "work.backup-2026-07-13"
        wb.mkdir()
        # No real files inside (only .DS_Store would be ignored)
        report = run_migration(tmp_path, force=True)
        assert not wb.exists(), (
            f"Leeres work.backup-2026-07-13/ wurde NICHT umbenannt: {wb}"
        )
        # It should have been moved to *.legacy-empty-<ts>/
        renamed = report["work_leftovers"]["renamed"]
        assert any(
            r.get("from", "").endswith("/work.backup-2026-07-13")
            for r in renamed
        ), f"work.backup-2026-07-13/ fehlt in renamed: {renamed}"
        # On disk: there must be a matching *.legacy-empty-* dir
        targets = list(tmp_path.glob("work.backup-2026-07-13.legacy-empty-*"))
        assert targets, f"Kein legacy-empty-<ts>/ Zielverzeichnis: {list(tmp_path.iterdir())}"
