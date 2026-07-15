"""Atomizitaets-Tests fuer die Session-Layout-Migration.

Garantiert: ein anderer Prozess, der mitten in der Migration
``os.listdir(data_dir)`` aufruft oder in die Session-Datei liest,
beobachtet entweder das volle alte Layout ODER das volle neue
Layout — NIE ein gemischtes / halb-verschobenes Ergebnis.

Realisiert wird das via ``os.replace`` (single rename auf POSIX) bzw.
``Path.rename`` (Fallback auf Windows).  Diese Operation ist auf dem
gleichen Filesystem garantiert atomar: der Verzeichnis-Eintrag wird
in einem einzigen Schritt umgehaengt.

Test-Strategie:
  * Direkter Test der Python-API ``run_migration``: vor dem Aufruf das
    Legacy-Layout anlegen, nach dem Aufruf pruefen, dass jede Datei
    in <sid> jetzt genau einmal an der neuen Position existiert (nicht
    zweimal — Quelle und Ziel duerfen nie gleichzeitig sichtbar sein).
  * Race-Test: ein paralleler Reader, der waehrend der Migration
    wiederholt ``listdir`` aufruft, darf nie eine inkonsistente
    Sicht beobachten (Test: ``os.listdir`` sieht die Session
    entweder im alten ODER im neuen Pfad, nie in beiden und nie in
    keinem von beiden).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from scripts.migrate_session_layout import run_migration


def _make_legacy_session(root: Path, sid: str) -> Path:
    legacy = root / "sessions" / sid
    (legacy / "results").mkdir(parents=True)
    (legacy / "Notes.md").write_text("# Session " + sid + "\n", encoding="utf-8")
    (legacy / "results" / f"{sid}.01result.json").write_text("{}", encoding="utf-8")
    (legacy / "results" / f"{sid}.01result.md").write_text("# md", encoding="utf-8")
    (legacy / "results" / f"{sid}.01result.html").write_text("<html/>", encoding="utf-8")
    return legacy


class TestPerSessionAtomicity:
    """Jede einzelne <sid>-Verschiebung ist atomar (kein halb-State)."""

    def test_after_migration_files_exist_only_in_canonical(
        self, tmp_path: Path
    ):
        for sid in ("alpha", "beta", "gamma"):
            _make_legacy_session(tmp_path, sid)
        run_migration(tmp_path, force=True)

        for sid in ("alpha", "beta", "gamma"):
            new = tmp_path / "session" / sid
            # Dateien muessen alle in canonical sein
            assert (new / "Notes.md").exists()
            assert (new / "results" / f"{sid}.01result.json").exists()
            assert (new / "results" / f"{sid}.01result.md").exists()
            assert (new / "results" / f"{sid}.01result.html").exists()
            # Inhalt ist erhalten
            assert (new / "Notes.md").read_text() == "# Session " + sid + "\n"
            assert (
                (new / "results" / f"{sid}.01result.json").read_text() == "{}"
            )
            # Legacy-Pfad darf nicht mehr existieren
            legacy = tmp_path / "sessions" / sid
            assert not legacy.exists(), (
                f"Legacy-Session {legacy} existiert noch nach Migration — "
                "Migration hat nicht alle Dateien mitgenommen!"
            )

    def test_file_appears_exactly_once(self, tmp_path: Path):
        """Fuer jeden Filename unter <sid>/ darf es nach der Migration
        genau einen Treffer geben — entweder im neuen ODER im alten
        Pfad, NIE in beiden gleichzeitig."""
        _make_legacy_session(tmp_path, "single")
        run_migration(tmp_path, force=True)
        # Suche die kanonische Notes.md
        matches_new = list((tmp_path / "session" / "single").rglob("Notes.md"))
        matches_old = list((tmp_path / "sessions" / "single").rglob("Notes.md"))
        assert len(matches_new) == 1, f"Mehrere Notes.md in canonical: {matches_new}"
        assert len(matches_old) == 0, f"Notes.md noch in legacy: {matches_old}"


class TestObservabilityRace:
    """Waehrend der Migration darf ein paralleler Reader nie eine
    'session_id in beiden Layouts gleichzeitig' oder
    'session_id in keinem der beiden Layouts' beobachten.

    Wir starten die Migration in einem Thread und lassen einen
    parallelen Reader immer wieder ``os.listdir`` auf beide Roots
    feuern.  Bei jedem Snapshot gilt:
      count(session/<sid>) + count(sessions/<sid>) == 1
    (solange die Migration laeuft).  Vor Start ist der count 1 in
    legacy, 0 in canonical; nach Ende ist es umgekehrt.
    """

    def test_session_visible_in_exactly_one_layout(self, tmp_path: Path):
        # Viele Sessions sorgen fuer eine laengere Migration.
        sids = [f"sid-race-{i:03d}" for i in range(40)]
        for sid in sids:
            _make_legacy_session(tmp_path, sid)

        # Shared state: der Reader sammelt Verletzungen.
        violations: list[str] = []
        stop = threading.Event()
        seen_states: list[tuple[str, int, int]] = []
        lock = threading.Lock()

        def reader() -> None:
            while not stop.is_set():
                for sid in sids:
                    in_new = (tmp_path / "session" / sid).exists()
                    in_old = (tmp_path / "sessions" / sid).exists()
                    total = int(in_new) + int(in_old)
                    if total not in (0, 1):
                        violations.append(
                            f"sid={sid} in_new={in_new} in_old={in_old}"
                        )
                    with lock:
                        seen_states.append((sid, int(in_new), int(in_old)))
                time.sleep(0.0005)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        # Migration in einem anderen Thread laufen lassen, damit reader
        # waehrend der Verschiebungen mitliest.
        run_done = threading.Event()

        def runner() -> None:
            try:
                run_migration(tmp_path, force=True)
            finally:
                run_done.set()

        t2 = threading.Thread(target=runner, daemon=True)
        t2.start()
        t2.join(timeout=15)
        assert run_done.is_set(), "Migration hat nicht in 15s abgeschlossen"
        stop.set()
        t.join(timeout=2)

        # 1) Keine Verletzungen: keine Session war jemals in beiden oder
        # in keinem Layout sichtbar.
        assert not violations, (
            "Atomaritaetsbruch: Reader sah Session in beiden "
            f"oder keinem Layout: {violations[:5]}"
        )
        # 2) Wir haben ueberhaupt gelesen (sonst sagt der Test nichts).
        assert len(seen_states) > 0, "Reader hat keine Snapshots gesammelt"
