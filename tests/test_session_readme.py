"""Tests fuer ``app.session_store.write_session_readme`` (Phase 5, v1.2.0).

Contract (spec / PR-body):
  * First ``write_result`` for a session creates ``session_readme.txt``.
  * Subsequent ``write_result`` calls rewrite the readme in full
    (atomic temp + ``os.replace``) so the file always reflects the
    full call history.
  * Service-agnostic: ``## Video context`` only appears when a
    YouTube-style call is detected; otherwise ``## Resource context``
    is rendered from the request body minus ``sessionId``.
  * File-list section enumerates the actual filenames in ``results/``
    (regression: ``*.01result.json`` style names must appear).
  * Backward-compat: legacy ``data/sessions/<sid>/`` layout is
    accepted via ``resolve_session_dir``.

These tests pin the contract and exercise both the happy path and
the service-agnostic branch.  Failure-path coverage (best-effort
logging) is verified by monkeypatching ``_atomic_write_text`` to raise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import session_store
from app.config import Settings
from app.session_store import (
    get_results_dir,
    get_session_dir,
    write_result,
    write_session_readme,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Setze ``settings.data_dir`` auf ``tmp_path`` fuer die Test-Sandbox."""
    session_store.settings.data_dir = str(tmp_path)
    return Settings(api_key="test", data_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: First call writes readme with correct header + initial row
# ---------------------------------------------------------------------------


class TestFirstCallWritesReadme:
    """Spec AC-1 + AC-3: erster Call erzeugt ``session_readme.txt`` und
    einen initialen Eintrag in der Calls-Tabelle."""

    def test_first_call_creates_readme(self, isolated_data_dir):
        sid = "sid-first"
        write_session_readme(
            sid,
            "get-metadata",
            {"success": True, "title": "Hello"},
            request={"sessionId": sid, "url": "https://youtu.be/dQw4w9WgXcQ"},
        )
        readme = get_session_dir(sid) / "session_readme.txt"
        assert readme.exists(), "session_readme.txt not created on first call"
        body = _read_text(readme)
        # Header contains the session id
        assert sid in body, f"session id missing in readme: {body[:200]}"
        # Service id + version surfaced
        assert "ME4-YOUTUBE" in body, (
            f"service id not in readme: {body[:200]}"
        )
        assert "1.2.0" in body, f"service version not in readme: {body[:200]}"

    def test_first_call_has_created_at_and_updated_at(self, isolated_data_dir):
        sid = "sid-first-ts"
        write_session_readme(
            sid, "get-metadata",
            {"success": True}, request={"sessionId": sid},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "Created:" in body, f"missing 'Created:' line: {body[:200]}"
        assert "Last updated:" in body, (
            f"missing 'Last updated:' line: {body[:200]}"
        )

    def test_first_call_has_calls_table_with_one_row(
        self, isolated_data_dir
    ):
        sid = "sid-first-row"
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "X"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        # Calls table
        assert "## Calls" in body, f"missing '## Calls' header: {body[:200]}"
        # Table header
        assert "NN" in body and "function" in body, (
            f"missing table columns: {body[:200]}"
        )
        # Function name appears in the table body
        assert "get-metadata" in body, (
            f"function_name missing in calls table: {body[:200]}"
        )
        # URL appears in the input column (input summary)
        assert "https://youtu.be/abc" in body, (
            f"URL not in input column: {body[:200]}"
        )

    def test_sidecar_meta_is_written_on_first_call(
        self, isolated_data_dir
    ):
        sid = "sid-first-meta"
        write_session_readme(
            sid, "get-metadata",
            {"success": True}, request={"sessionId": sid, "url": "..."},
        )
        meta_path = get_session_dir(sid) / "session_readme_meta.json"
        assert meta_path.exists(), "sidecar JSON not created"
        meta = json.loads(_read_text(meta_path))
        assert meta["session_id"] == sid
        assert meta["service_id"] == "ME4-YOUTUBE"
        assert meta["service_version"] == "1.2.0"
        assert isinstance(meta["calls"], list)
        assert len(meta["calls"]) == 1
        assert meta["calls"][0]["function_name"] == "get-metadata"


# ---------------------------------------------------------------------------
# Test 2: Second call updates readme with both calls in the table
# ---------------------------------------------------------------------------


class TestSecondCallUpdatesReadme:
    """Spec AC-3: jeder weitere Call rewritet die Readme vollstaendig.
    Die Calls-Tabelle enthaelt nach 2 Calls zwei Zeilen."""

    def test_second_call_appends_call_row(self, isolated_data_dir):
        sid = "sid-second"
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "Call 1"},
            request={"sessionId": sid, "url": "https://youtu.be/v1"},
        )
        write_session_readme(
            sid, "get-transcript",
            {"success": True},
            request={"sessionId": sid, "url": "https://youtu.be/v1",
                     "language": "de"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "get-metadata" in body
        assert "get-transcript" in body
        # Both URLs appear (or at least the host part)
        assert "v1" in body, "first-call URL vanished after second call"

    def test_sidecar_tracks_all_calls(self, isolated_data_dir):
        sid = "sid-second-meta"
        for fn, req in (
            ("get-metadata", {"sessionId": sid, "url": "https://youtu.be/a"}),
            ("get-transcript", {"sessionId": sid, "url": "https://youtu.be/a",
                                "language": "de"}),
            ("download", {"sessionId": sid, "url": "https://youtu.be/a",
                          "audio_only": True}),
        ):
            write_session_readme(
                sid, fn, {"success": True}, request=req,
            )
        meta_path = get_session_dir(sid) / "session_readme_meta.json"
        meta = json.loads(_read_text(meta_path))
        assert len(meta["calls"]) == 3
        assert [c["function_name"] for c in meta["calls"]] == [
            "get-metadata", "get-transcript", "download",
        ]

    def test_created_at_preserved_last_updated_advances(
        self, isolated_data_dir
    ):
        sid = "sid-ts"
        write_session_readme(
            sid, "get-metadata", {"success": True},
            request={"sessionId": sid, "url": "https://youtu.be/x"},
        )
        meta_path = get_session_dir(sid) / "session_readme_meta.json"
        m1 = json.loads(_read_text(meta_path))
        write_session_readme(
            sid, "get-transcript", {"success": True},
            request={"sessionId": sid, "url": "https://youtu.be/x"},
        )
        m2 = json.loads(_read_text(meta_path))
        # created_at is stable
        assert m1["created_at"] == m2["created_at"], (
            f"created_at drifted: {m1['created_at']} -> {m2['created_at']}"
        )
        # last_updated_at may advance (or be equal if same second)
        assert m2["last_updated_at"] >= m1["last_updated_at"]


# ---------------------------------------------------------------------------
# Test 3: YouTube call populates "## Video context"
# ---------------------------------------------------------------------------


class TestYouTubeVideoContext:
    """Spec: YouTube-Calls rendern ``## Video context`` mit URL + video_id
    + title (aus dem ersten Metadata-Resultat)."""

    def test_youtube_call_renders_video_context(self, isolated_data_dir):
        sid = "sid-yt"
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "Never Gonna Give You Up",
             "video_id": "dQw4w9WgXcQ"},
            request={"sessionId": sid,
                     "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "## Video context" in body, (
            f"YouTube call did not render '## Video context': {body[:400]}"
        )
        assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in body
        assert "dQw4w9WgXcQ" in body
        assert "Never Gonna Give You Up" in body
        # Resource-context must NOT appear (mutually exclusive)
        assert "## Resource context" not in body, (
            "Video context + Resource context both rendered (must be exclusive)"
        )

    def test_video_context_uses_first_call_only(self, isolated_data_dir):
        """Spec: 'from first metadata result' -- subsequent calls keep the
        original URL/title even if the later request has a different URL."""
        sid = "sid-yt-first"
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "First Video", "video_id": "vid1"},
            request={"sessionId": sid, "url": "https://youtu.be/vid1"},
        )
        # Second call has a different URL/title -- should NOT overwrite
        write_session_readme(
            sid, "get-transcript",
            {"success": True, "title": "Second Video", "video_id": "vid2"},
            request={"sessionId": sid, "url": "https://youtu.be/vid2"},
        )
        meta_path = get_session_dir(sid) / "session_readme_meta.json"
        meta = json.loads(_read_text(meta_path))
        vc = meta.get("video_context") or {}
        assert vc.get("url") == "https://youtu.be/vid1", (
            f"video_context URL overwritten: {vc}"
        )
        assert vc.get("video_id") == "vid1"
        assert vc.get("title") == "First Video"

    def test_youtube_detection_via_url_only(self, isolated_data_dir):
        """Non-canonical function_name but YouTube URL -> still video context."""
        sid = "sid-yt-urlonly"
        write_session_readme(
            sid, "custom-pipeline",
            {"success": True, "title": "Detected via URL"},
            request={"sessionId": sid,
                     "url": "https://youtu.be/abcdef12345"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "## Video context" in body, (
            f"YouTube URL alone did not trigger Video context: {body[:400]}"
        )


# ---------------------------------------------------------------------------
# Test 4: Non-YouTube call uses "## Resource context" (no Video context)
# ---------------------------------------------------------------------------


class TestNonYouTubeResourceContext:
    """Service-agnostisch: ein generischer Call bekommt ``## Resource
    context`` mit dem rohen Request-Body minus ``sessionId``."""

    def test_non_youtube_call_renders_resource_context(
        self, isolated_data_dir
    ):
        sid = "sid-non-yt"
        write_session_readme(
            sid, "my-custom-fn",
            {"success": True, "output": "/tmp/out.txt"},  # noqa: S108
            request={"sessionId": sid, "input_file": "/tmp/in.txt",  # noqa: S108
                     "format": "json", "lang": "de"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        # NO Video context
        assert "## Video context" not in body, (
            f"non-YouTube call wrongly rendered Video context: {body[:400]}"
        )
        # Resource context IS rendered
        assert "## Resource context" in body, (
            f"non-YouTube call did not render Resource context: {body[:400]}"
        )
        # Raw request body fields appear (minus sessionId)
        assert "input_file" in body
        assert "format" in body
        assert "lang" in body
        # sessionId stripped from the kv lines (the section description
        # legitimately mentions ``sessionId`` as a word).  Look at the
        # k: v lines specifically (those starting with ``- ``).
        rc_section = body.split("## Resource context", 1)[1]
        kv_lines = [
            ln for ln in rc_section.splitlines()
            if ln.startswith("- ")
        ]
        assert kv_lines, "no kv lines in Resource context"
        joined_kv = "\n".join(kv_lines)
        assert "sessionId" not in joined_kv, (
            f"sessionId leaked into Resource context kv lines: {kv_lines}"
        )

    def test_first_video_then_non_video_promotes_to_video(
        self, isolated_data_dir
    ):
        """If the session started with a video call, subsequent non-video
        calls keep the Video-context block (no regression)."""
        sid = "sid-mixed"
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "V1", "video_id": "v1"},
            request={"sessionId": sid, "url": "https://youtu.be/v1"},
        )
        write_session_readme(
            sid, "my-custom-fn",
            {"success": True},
            request={"sessionId": sid, "input": "something"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "## Video context" in body
        assert "## Resource context" not in body


# ---------------------------------------------------------------------------
# Test 5: file-list section uses actual filenames from results/
# ---------------------------------------------------------------------------


class TestFilesListFromResultsDir:
    """Spec: die File-Listing-Section nennt die echten Dateinamen aus
    ``results/`` (Regression: ``*.01result.json`` style names erscheinen)."""

    def test_readme_lists_canonical_resultset_files(
        self, isolated_data_dir
    ):
        sid = "sid-files"
        # Echtes write_result, damit die Resultset-Dateien existieren
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Listing"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "Listing"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "## Files in `results/`" in body, (
            f"missing files section: {body[:400]}"
        )
        # Konkrete kanonische Dateinamen
        assert f"{sid}.01result.json" in body, (
            f".01result.json nicht im Listing: {body[:400]}"
        )
        assert f"{sid}.01result.md" in body
        assert f"{sid}.01result.html" in body

    def test_readme_lists_files_with_sizes_and_mtimes(
        self, isolated_data_dir
    ):
        sid = "sid-sizes"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Sizes"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        write_session_readme(
            sid, "get-metadata",
            {"success": True},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        # Mindestens eine Zeile mit Bytes-Angabe
        assert "bytes" in body, (
            f"no 'bytes' suffix in file listing: {body[:600]}"
        )

    def test_readme_lists_two_sequential_resultsets(
        self, isolated_data_dir
    ):
        """Nach zwei ``write_result``-Calls listet die Readme BEIDE
        Resultsets (.01 + .02) -- kein Ueberschreiben, kein Verschwinden."""
        sid = "sid-seq"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "A"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        write_result(
            sid, "get-transcript",
            {"success": True, "title": "B"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        write_session_readme(
            sid, "get-transcript",
            {"success": True, "title": "B"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert f"{sid}.01result.json" in body, (
            f".01result.json fehlt nach 2 Calls: {body[:600]}"
        )
        assert f"{sid}.02result.json" in body, (
            f".02result.json fehlt nach 2 Calls: {body[:600]}"
        )

    def test_files_listing_omits_directories(
        self, isolated_data_dir
    ):
        """Verzeichnisse im results/-Verzeichnis werden nicht aufgelistet."""
        sid = "sid-dirs"
        write_result(
            sid, "get-metadata",
            {"success": True}, request={"sessionId": sid, "url": "..."},
        )
        # Legacy-Per-Function-Subdir reinpflanzen
        rd = get_results_dir(sid)
        subdir = rd / "01-get-metadata"
        subdir.mkdir()
        write_session_readme(
            sid, "get-metadata",
            {"success": True}, request={"sessionId": sid, "url": "..."},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        # Files-Section nennt nicht das Subdir
        files_section = body.split("## Files in `results/`", 1)[1]
        assert "01-get-metadata" not in files_section, (
            f"subdir leaked into file listing: {files_section[:400]}"
        )


# ---------------------------------------------------------------------------
# Test 6: legacy `data/sessions/<sid>/` layout
# ---------------------------------------------------------------------------


class TestLegacyLayoutCompat:
    """Spec: ``write_session_readme`` akzeptiert das legacy
    ``data/sessions/<sid>/``-Layout (ueber ``resolve_session_dir``)."""

    def test_readme_written_into_legacy_layout(
        self, isolated_data_dir, tmp_path: Path
    ):
        # Legacy-Layout manuell anlegen (singular NICHT existent)
        legacy = tmp_path / "sessions" / "sid-legacy"
        legacy.mkdir(parents=True)
        (legacy / "results").mkdir()
        (legacy / "results" / "sid-legacy.01result.json").write_text(
            "{}", encoding="utf-8",
        )

        write_session_readme(
            "sid-legacy", "get-metadata",
            {"success": True, "title": "Legacy"},
            request={"sessionId": "sid-legacy",
                     "url": "https://youtu.be/abc"},
        )
        # Readme landet im LEGACY-Layout (weil nur das existiert)
        assert (legacy / "session_readme.txt").exists(), (
            f"readme nicht in legacy-Layout geschrieben: {legacy}"
        )
        # Readme enthaelt die kanonischen Inhalte
        body = _read_text(legacy / "session_readme.txt")
        assert "sid-legacy" in body
        assert ".01result.json" in body
        # Singular-Layout wurde NICHT angelegt
        assert not (tmp_path / "session" / "sid-legacy").exists(), (
            "write_session_readme hat unerwartet canonical-Layout angelegt"
        )

    def test_legacy_session_id_sanitised(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Unerlaubte Zeichen in der Session-ID werden wie ueblich
        sanitisiert (alnum + ``-`` + ``_``).  ``"sid with specials!"``
        wird zu ``"sidwithspecials"`` (spaces, ``!`` raus)."""
        # Compute safe_id the same way as resolve_session_dir does.
        safe_id = "".join(
            c for c in "sid with specials!" if c.isalnum() or c in "-_"
        ) or "unknown"
        assert safe_id == "sidwithspecials", (
            f"unexpected sanitisation result: {safe_id!r}"
        )
        legacy = tmp_path / "sessions" / safe_id
        legacy.mkdir(parents=True)
        write_session_readme(
            "sid with specials!",
            "get-metadata", {"success": True},
            request={"sessionId": "sid with specials!"},
        )
        # Sanitisierter Pfad wurde genutzt
        assert (legacy / "session_readme.txt").exists(), (
            f"readme nicht am sanitisierten legacy-Pfad: "
            f"{legacy / 'session_readme.txt'}"
        )


# ---------------------------------------------------------------------------
# Test 7: atomicity + best-effort guarantees
# ---------------------------------------------------------------------------


class TestAtomicityAndBestEffort:
    """Spec: write_session_readme ist best-effort und blockiert den
    write_result-Pfad nicht."""

    def test_atomic_rewrite_does_not_leave_temp_files(
        self, isolated_data_dir
    ):
        sid = "sid-atomic"
        for i in range(3):
            write_session_readme(
                sid, f"fn-{i}",
                {"success": True},
                request={"sessionId": sid, "url": f"https://youtu.be/v{i}"},
            )
        # Keine .tmp-Files uebrig
        leftover = list(
            get_session_dir(sid).glob(".session_readme*.tmp")
        )
        assert leftover == [], f"temp files leaked: {leftover}"

    def test_readme_failure_does_not_raise(
        self, isolated_data_dir, monkeypatch
    ):
        """Selbst wenn der Write scheitert, darf KEINE Exception hochschlagen
        -- der write_result-Pfad muss weiterlaufen."""
        sid = "sid-best-effort"

        def boom(*args, **kwargs):
            raise OSError("simulated disk full")

        monkeypatch.setattr(
            session_store, "_atomic_write_text", boom,
        )
        # Darf NICHT raisen
        write_session_readme(
            sid, "get-metadata",
            {"success": True},
            request={"sessionId": sid, "url": "https://youtu.be/x"},
        )

    def test_write_result_call_continues_when_readme_fails(
        self, isolated_data_dir, monkeypatch
    ):
        """Integration: ``write_result`` ruft ``write_session_readme``,
        und selbst wenn die Readme scheitert, muss ``write_result`` die
        Resultset-Dateien normal schreiben + returnen."""
        sid = "sid-int"

        def boom(*args, **kwargs):
            raise OSError("simulated readme failure")

        monkeypatch.setattr(
            session_store, "write_session_readme", boom,
        )
        # write_result darf nicht crashen, Resultset muss trotzdem da sein
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Best effort"},
            request={"sessionId": sid, "url": "https://youtu.be/x"},
        )
        assert result.get("success") is True, (
            f"write_result hat success geflippt obwohl nur Readme scheiterte: "
            f"{result!r}"
        )
        # Resultset-Files sind trotzdem geschrieben
        rd = get_results_dir(sid)
        for ext in ("json", "md", "html"):
            assert (rd / f"{sid}.01result.{ext}").exists(), (
                f"resultset-Datei fehlt nach Readme-Failure: "
                f"{sid}.01result.{ext}"
            )


# ---------------------------------------------------------------------------
# Test 8: end-to-end through write_result
# ---------------------------------------------------------------------------


class TestWriteResultHook:
    """``write_result`` ruft ``write_session_readme`` automatisch auf."""

    def test_write_result_creates_readme(self, isolated_data_dir):
        sid = "sid-hook"
        # Kein expliziter write_session_readme-Aufruf
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Hooked"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        readme = get_session_dir(sid) / "session_readme.txt"
        assert readme.exists(), (
            "write_result hat session_readme.txt nicht erzeugt"
        )
        body = _read_text(readme)
        assert "get-metadata" in body
        assert "https://youtu.be/abc" in body

    def test_two_write_result_calls_accumulate_in_readme(
        self, isolated_data_dir
    ):
        sid = "sid-hook-2"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "A"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        write_result(
            sid, "get-transcript",
            {"success": True},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        body = _read_text(get_session_dir(sid) / "session_readme.txt")
        assert "get-metadata" in body
        assert "get-transcript" in body
        # Calls-Tabelle enthaelt beide Funktionen
        calls_section = body.split("## Calls", 1)[1].split("##", 1)[0]
        assert "get-metadata" in calls_section
        assert "get-transcript" in calls_section


# ---------------------------------------------------------------------------
# Test 9: file format guarantees (UTF-8, LF, no CRLF)
# ---------------------------------------------------------------------------


class TestFileFormatGuarantees:
    """Spec AC-5: UTF-8, LF newlines, no CRLF."""

    def test_readme_is_utf8(self, isolated_data_dir):
        sid = "sid-utf8"
        write_session_readme(
            sid, "get-metadata",
            {"success": True, "title": "Hello with umlauts: äöü"},
            request={"sessionId": sid, "url": "https://youtu.be/abc"},
        )
        readme = get_session_dir(sid) / "session_readme.txt"
        raw = readme.read_bytes()
        # Decode as utf-8 must succeed without error
        text = raw.decode("utf-8")
        assert "äöü" in text, "non-ASCII characters lost"

    def test_readme_has_no_crlf(self, isolated_data_dir):
        sid = "sid-no-crlf"
        write_session_readme(
            sid, "get-metadata",
            {"success": True}, request={"sessionId": sid, "url": "..."},
        )
        raw = (get_session_dir(sid) / "session_readme.txt").read_bytes()
        assert b"\r\n" not in raw, (
            f"CRLF found in readme: {raw[:200]!r}"
        )
