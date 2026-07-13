r"""Phase-4 Persistenz- und Contract-Tests (Spec YT-08 + YT-05 + YT-06).

Bezug: .spec/offen/me4-ui-service-owned-interaction-v1-audit-2026-07-12.md
       § "Anforderungsliste ME4-S-youtube" → YT-05, YT-06, YT-08.

Diese Tests sind die explizite YT-08-Lieferung der Phase 4 und dokumentieren
die Vertragspflicht aus der BPSpec 1:1 als nummerierte Test-Cases (YT-08-1
.. YT-08-7).  Sie sind ergaenzend zu ``tests/test_seq_parser.py`` und
``tests/test_dir_contract.py``: dort sind F-05, YT-02, YT-03, YT-04 und
die Sequential-Regression bereits abgedeckt; hier fuegen wir die YT-08-
Pflicht-Cases explizit hinzu und ergaenzen YT-05 (Write-Komplett-Garantie)
sowie YT-06 (awaitInput service-owned).

Test-Strategie:
    * Reine Logik-Tests, soweit moeglich; ruft ``write_result`` und
      ``build_summary`` direkt auf.
    * Test 7 (awaitInput) geht durch den FastAPI-TestClient, weil das
      die einzige Stelle ist, an der ``_URL_FIELD`` und
      ``_await_input`` zu einer HTTP-Response zusammengesetzt werden.
    * ``tmp_path`` als ``settings.data_dir``-Root, damit alle
      Pfad-Funktionen in der Sandbox schreiben.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import session_store
from app.config import Settings
from app.response_contract import build_summary
from app.session_store import (
    get_results_dir,
    get_session_dir,
    write_result,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Setze ``settings.data_dir`` auf ``tmp_path`` fuer die Test-Sandbox."""
    session_store.settings.data_dir = str(tmp_path)
    return Settings(api_key="test", data_dir=str(tmp_path))


def _touch(p: Path, body: str = "{}") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# YT-08-1: WORK_DIR/session/<sid>/results wird erzeugt
# ---------------------------------------------------------------------------


class TestYT08_01_ResultsDirCreated:
    """Spec YT-08 Case 1: ``WORK_DIR/session/<sid>/results`` wird erzeugt
    sobald der erste ``write_result``-Call fuer ``<sid>`` laeuft.

    Pfad-Konvention (Master-Doku): ``<WORK_DIR>/sessions/<sid>/results``
    (siehe ``get_session_dir`` + ``get_results_dir`` in
    ``app/session_store.py``).
    """

    def test_results_dir_exists_after_first_call(
        self, isolated_data_dir, tmp_path: Path
    ):
        sid = "yt08sid01"
        # Vor dem Call existiert weder Session- noch Results-Verzeichnis
        session_dir = tmp_path / "sessions" / sid
        results_dir = session_dir / "results"
        assert not results_dir.exists()

        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Erster Call"},
            request={"sessionId": sid, "url": "https://x"},
        )

        # Nach dem Call existieren BEIDE Verzeichnisse (Sandbox ist
        # settings.data_dir = tmp_path).
        assert session_dir.exists(), (
            f"Session-Root fehlt: {session_dir}"
        )
        assert results_dir.exists(), (
            f"Results-Verzeichnis fehlt nach erstem Call: {results_dir}"
        )
        assert results_dir.is_dir(), (
            f"Results-Verzeichnis ist keine Directory: {results_dir}"
        )

    def test_results_dir_path_shape(
        self, isolated_data_dir, tmp_path: Path
    ):
        """Pfad-Form exakt: ``<data_dir>/sessions/<sid>/results``."""
        sid = "yt08path01"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Shape"},
            request={"sessionId": sid, "url": "https://x"},
        )
        results_dir = get_results_dir(sid)
        expected = (tmp_path / "sessions" / sid / "results").resolve()
        assert results_dir.resolve() == expected, (
            f"Results-Pfad weicht vom erwarteten Master-Schema ab: "
            f"{results_dir.resolve()} vs {expected}"
        )


# ---------------------------------------------------------------------------
# YT-08-2: erster Aufruf schreibt .01result.* (json, md, html)
# ---------------------------------------------------------------------------


class TestYT08_02_FirstCallWrites01:
    """Spec YT-08 Case 2: der erste Aufruf schreibt exakt die drei
    kanonischen Resultset-Dateien ``<sid>.01result.{json,md,html}``.
    """

    def test_first_call_writes_canonical_three_files(
        self, isolated_data_dir
    ):
        sid = "yt08sid02"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Erster Call", "channel": "Ch"},
            request={"sessionId": sid, "url": "https://youtu.be/dQw4w9WgXcQ"},
        )

        rd = get_results_dir(sid)
        # Drei kanonische Dateien muessen EXISTIEREN.
        for ext in ("json", "md", "html"):
            p = rd / f"{sid}.01result.{ext}"
            assert p.exists(), (
                f"{ext}-Datei fehlt nach erstem Call: {p}"
            )

        # JSON-Datei ist valides JSON.
        json_body = json.loads(
            (rd / f"{sid}.01result.json").read_text(encoding="utf-8")
        )
        assert json_body.get("success") is True
        assert json_body.get("title") == "Erster Call"

        # MD-Datei ist nicht-leer (>=1 Byte) und enthaelt Title als
        # Heading.
        md_body = (rd / f"{sid}.01result.md").read_text(encoding="utf-8")
        assert len(md_body) >= 1, "MD-Datei ist leer"
        assert "Erster Call" in md_body, (
            f"MD enthaelt den Title nicht: {md_body[:200]!r}"
        )

        # HTML-Datei ist nicht-leer und enthaelt ein HTML-Grundgeruest.
        html_body = (rd / f"{sid}.01result.html").read_text(encoding="utf-8")
        assert len(html_body) >= 1, "HTML-Datei ist leer"
        assert "<html" in html_body.lower(), (
            f"HTML-Datei hat kein <html>-Tag: {html_body[:200]!r}"
        )

        # YT-05: alle drei >=1 Byte.
        for ext in ("json", "md", "html"):
            size = (rd / f"{sid}.01result.{ext}").stat().st_size
            assert size >= 1, (
                f"{ext}-Datei kleiner 1 Byte (Spec YT-05 verletzt): {size}"
            )


# ---------------------------------------------------------------------------
# YT-08-3: zweiter Aufruf schreibt .02result.* und ueberschreibt .01 NICHT
# ---------------------------------------------------------------------------


class TestYT08_03_SecondCallNoOverwrite:
    """Spec YT-08 Case 3: zwei aufeinanderfolgende Calls erzeugen
    ``.01result.*`` und ``.02result.*``, ohne dass ``.01`` ueberschrieben
    wird.
    """

    def test_two_calls_no_overwrite(self, isolated_data_dir):
        sid = "yt08sid03"
        # 1. Call
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "CallEins", "channel": "Ch"},
            request={"sessionId": sid, "url": "https://a"},
        )
        # 2. Call
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "CallZwei", "channel": "Ch"},
            request={"sessionId": sid, "url": "https://b"},
        )

        rd = get_results_dir(sid)
        # BEIDE Resultsets existieren.
        for nn in ("01", "02"):
            for ext in ("json", "md", "html"):
                assert (rd / f"{sid}.{nn}result.{ext}").exists(), (
                    f"{sid}.{nn}result.{ext} fehlt nach 2 Calls"
                )

        # Inhalt von NN=01 darf NICHT von NN=02 ueberschrieben worden sein.
        json_01 = json.loads(
            (rd / f"{sid}.01result.json").read_text(encoding="utf-8")
        )
        json_02 = json.loads(
            (rd / f"{sid}.02result.json").read_text(encoding="utf-8")
        )
        assert json_01.get("title") == "CallEins", (
            f"NN=01 wurde ueberschrieben: title={json_01.get('title')!r}"
        )
        assert json_02.get("title") == "CallZwei"

        md_01 = (rd / f"{sid}.01result.md").read_text(encoding="utf-8")
        assert "CallEins" in md_01 and "CallZwei" not in md_01, (
            "NN=01 MD enthaelt Inhalte aus NN=02 -- wurde ueberschrieben."
        )
        md_02 = (rd / f"{sid}.02result.md").read_text(encoding="utf-8")
        assert "CallZwei" in md_02

        html_01 = (rd / f"{sid}.01result.html").read_text(encoding="utf-8")
        assert "CallEins" in html_01
        html_02 = (rd / f"{sid}.02result.html").read_text(encoding="utf-8")
        assert "CallZwei" in html_02


# ---------------------------------------------------------------------------
# YT-08-4: dirAbsolute == filesSavedTo == resultsDir
# ---------------------------------------------------------------------------


class TestYT08_04_TripleAlias:
    """Spec YT-08 Case 4 + AC-4: ``dirAbsolute``, ``filesSavedTo`` und
    ``resultsDir`` zeigen auf dasselbe Results-Verzeichnis.
    """

    def test_three_directory_aliases_are_identical(self, isolated_data_dir):
        sid = "yt08sid04"
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Alias-Test"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary("get-metadata", result, session_id=sid)
        assert s["dirAbsolute"] == s["filesSavedTo"], (
            f"dirAbsolute vs filesSavedTo: "
            f"{s['dirAbsolute']!r} vs {s['filesSavedTo']!r}"
        )
        assert s["dirAbsolute"] == s["resultsDir"], (
            f"dirAbsolute vs resultsDir: "
            f"{s['dirAbsolute']!r} vs {s['resultsDir']!r}"
        )
        assert s["filesSavedTo"] == s["resultsDir"], (
            f"filesSavedTo vs resultsDir: "
            f"{s['filesSavedTo']!r} vs {s['resultsDir']!r}"
        )

    def test_aliases_point_to_results_subdir_not_session_root(
        self, isolated_data_dir
    ):
        """Spec: alle drei muessen auf ``results/`` zeigen, NICHT auf
        den Session-Root."""
        sid = "yt08sid04b"
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "X"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary("get-metadata", result, session_id=sid)
        for key in ("dirAbsolute", "filesSavedTo", "resultsDir"):
            v = s[key]
            assert v.endswith("/results"), (
                f"{key} endet nicht auf /results: {v!r}"
            )
        # Optional: sessionDir zeigt separat auf den Session-Root
        assert "sessionDir" in s
        assert not s["sessionDir"].endswith("/results")


# ---------------------------------------------------------------------------
# YT-08-5: alle Einzelpfade liegen INNERHALB dirAbsolute
# ---------------------------------------------------------------------------


class TestYT08_05_PathsWithinDirAbsolute:
    """Spec YT-08 Case 5 + UI-04 Validierungsschritt 4: ``jsonPath``,
    ``mdPath`` und ``htmlPath`` liegen jeweils lexikalisch unterhalb
    ``dirAbsolute``.
    """

    def test_all_three_paths_inside_dirabsolute(self, isolated_data_dir):
        sid = "yt08sid05"
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Path-Containment"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary("get-metadata", result, session_id=sid)
        d = Path(s["dirAbsolute"]).resolve()

        for key in ("jsonPath", "mdPath", "htmlPath"):
            p = Path(s[key]).resolve()
            # Parent-Identitaet (lexikografisch innerhalb).
            assert p.parent == d, (
                f"{key}={p!r} liegt nicht unter dirAbsolute={d!r}"
            )
            # Defensiv: startswith-Check (faengt z.B. /results2 ab).
            assert str(p).startswith(str(d) + os.sep), (
                f"{key}={p!r} ist nicht unterhalb von {d!r}"
            )

    def test_paths_inside_dirabsolute_for_two_sequential_results(
        self, isolated_data_dir
    ):
        """Containment-Garantie gilt auch fuer das 2. Resultset."""
        sid = "yt08sid05b"
        for i in (1, 2):
            r = write_result(
                sid, "get-metadata",
                {"success": True, "title": f"Call {i}"},
                request={"sessionId": sid, "url": f"https://x{i}"},
            )
            s = build_summary("get-metadata", r, session_id=sid)
            d = Path(s["dirAbsolute"]).resolve()
            for key in ("jsonPath", "mdPath", "htmlPath"):
                p = Path(s[key]).resolve()
                assert p.parent == d, (
                    f"Call {i}: {key}={p!r} nicht unter {d!r}"
                )


# ---------------------------------------------------------------------------
# YT-08-6: files[] entspricht 1:1 dem Filesystem-Listing von dirAbsolute
# ---------------------------------------------------------------------------


class TestYT08_06_FilesListMatchesFilesystem:
    """Spec YT-08 Case 6 + AC-4: ``files[]`` stimmt zu 100% mit dem echten
    Filesystem-Listing des Results-Verzeichnisses ueberein (nur die
    Dateien des aktuellen Resultsets, regex-gefiltert per
    ``_RESULT_RE``).
    """

    def test_files_list_matches_os_listdir(self, isolated_data_dir):
        sid = "yt08sid06"
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Listing"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary("get-metadata", result, session_id=sid)

        # Echte Filesystem-Sicht: alle Filenames, die zur aktuellen
        # NN gehoeren (regex _RESULT_RE, sid-Match, nn-Match).
        d = Path(s["dirAbsolute"]).resolve()
        fs_names = set()
        for entry in d.iterdir():
            if not entry.is_file():
                continue
            # Re-Regex analog zu list_resultset_files.
            import re
            from app.session_store import _RESULT_RE
            m = _RESULT_RE.match(entry.name)
            if m and m.group("sid") == sid:
                # NN muss zu den gemeldeten Pfaden passen; sonst ist es
                # ein Vorgaenger-Resultset und gehoert nicht in files[].
                # Wir nehmen das NN aus dem aktuellen jsonPath.
                m_cur = _RESULT_RE.match(Path(s["jsonPath"]).name)
                if m_cur and m.group("nn") == m_cur.group("nn"):
                    fs_names.add(entry.name)

        reported_names = {f["name"] for f in s["files"]}
        assert reported_names == fs_names, (
            f"files[] weicht vom Filesystem ab: "
            f"reported={reported_names}, fs={fs_names}"
        )

        # Jedes gemeldete File hat Pflicht-Felder name/size/mtimeMs.
        for f in s["files"]:
            assert set(f.keys()) == {"name", "size", "mtimeMs", "path", "openUrl"}
            real = d / f["name"]
            assert real.exists()
            assert f["size"] == real.stat().st_size
            assert f["mtimeMs"] == int(real.stat().st_mtime * 1000)

    def test_files_list_excludes_notes_md_and_dirs(self, isolated_data_dir):
        """Ablenker (Notes.md, Verzeichnisse, andere NNs) sind draussen."""
        sid = "yt08sid06b"
        rd_native = get_results_dir(sid)
        # write_result erzeugt NN=01
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Ablenker"},
            request={"sessionId": sid, "url": "https://x"},
        )
        # Manuell Notes.md + legacy subdir + Vorgenger-NN
        (rd_native / "Notes.md").write_text("# log", encoding="utf-8")
        (rd_native / "01-get-metadata").mkdir()
        (rd_native / "01-get-metadata" / "result.json").write_text("{}")
        # write_result nochmal -> NN=02
        result2 = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Zweiter Call"},
            request={"sessionId": sid, "url": "https://y"},
        )
        # build_summary auf den 2. Call -> files[] darf NUR NN=02 enthalten
        s = build_summary("get-metadata", result2, session_id=sid)
        reported_names = {f["name"] for f in s["files"]}
        assert "Notes.md" not in reported_names
        assert not any("01-get-metadata" in n for n in reported_names)
        # Kein NN=01 in NN=02-Listing
        assert not any(n.endswith(".01result.json") for n in reported_names)
        # Genau die 3 NN=02-Dateien
        assert reported_names == {
            f"{sid}.02result.html",
            f"{sid}.02result.json",
            f"{sid}.02result.md",
        }

    def test_files_list_size_accurate(self, isolated_data_dir):
        """Spec AC-4: gemeldete Files existieren wirklich + Size stimmt."""
        sid = "yt08sid06c"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "Size"},
            request={"sessionId": sid, "url": "https://x"},
        )
        s = build_summary(
            "get-metadata",
            {"jsonPath": str(get_results_dir(sid) / f"{sid}.01result.json")},
            session_id=sid,
        )
        d = Path(s["dirAbsolute"]).resolve()
        for f in s["files"]:
            real_size = (d / f["name"]).stat().st_size
            assert f["size"] == real_size, (
                f"size mismatch fuer {f['name']}: {f['size']} vs {real_size}"
            )


# ---------------------------------------------------------------------------
# YT-08-7: fehlende URL liefert korrektes awaitInput
# ---------------------------------------------------------------------------


class TestYT08_07_AwaitInputOnMissingUrl:
    """Spec YT-08 Case 7 + YT-06 + UI-02 + UI-06: ohne URL antwortet
    der Service mit einem ``awaitInput``-Envelope (Titel, Beschreibung,
    URL-Label, Typ, Required, Placeholder) -- nicht mit HTTP 400.
    """

    def _client(self):
        from fastapi.testclient import TestClient
        from app.http_api import build_app
        from app.loadbalancer import WorkerPool
        from app.zmq_service import ZMQService
        pool = WorkerPool(host="127.0.0.1", base_port=0, size=0)
        zmq = ZMQService(pool=pool, port=0)
        return TestClient(build_app(pool, zmq))

    def test_metadata_no_url_returns_await_input(self):
        """POST /api/metadata ohne URL -> awaitInput, kein 400."""
        client = self._client()
        # conftest setzt API_KEY=test-key, also header mitsenden.
        r = client.post(
            "/api/metadata",
            json={"sessionId": "yt08sid07"},
            headers={"X-API-Key": "test-key"},
        )
        assert r.status_code == 200, (
            f"awaitInput-Pfad sollte 200 liefern, nicht {r.status_code}: "
            f"{r.text[:200]}"
        )
        body = r.json()
        assert "awaitInput" in body, (
            f"Response enthaelt kein awaitInput: {body}"
        )

    def test_await_input_has_required_envelope_fields(self):
        """YT-06: Title + Description + URL-Feld (Label, Typ, Required,
        Placeholder)."""
        client = self._client()
        r = client.post(
            "/api/metadata",
            json={"sessionId": "yt08sid07b"},
            headers={"X-API-Key": "test-key"},
        )
        body = r.json()
        ai = body["awaitInput"]
        # Title (Pflicht)
        assert isinstance(ai.get("title"), str) and ai["title"].strip(), (
            f"awaitInput.title fehlt/leer: {ai.get('title')!r}"
        )
        # Description (Pflicht)
        assert isinstance(ai.get("description"), str) and ai["description"].strip(), (
            f"awaitInput.description fehlt/leer: {ai.get('description')!r}"
        )
        # Fields (mindestens das URL-Feld)
        assert isinstance(ai.get("fields"), list) and ai["fields"], (
            f"awaitInput.fields fehlt/leer: {ai.get('fields')!r}"
        )

        # URL-Feld mit den vom Service definierten Eigenschaften
        url_field = next(
            (f for f in ai["fields"] if f.get("name") == "url"), None
        )
        assert url_field is not None, (
            f"URL-Feld fehlt in fields: {ai['fields']}"
        )
        # Spec YT-06 Pflicht: Label, Typ, Required, Placeholder
        assert url_field.get("label"), "URL-Feld ohne label"
        assert url_field.get("type") == "url", (
            f"URL-Feld falscher Typ: {url_field.get('type')!r}"
        )
        assert url_field.get("required") is True, (
            "URL-Feld nicht required=True"
        )
        assert url_field.get("placeholder"), "URL-Feld ohne placeholder"

    def test_transcript_no_url_returns_await_input_with_extra_field(self):
        """Auch /api/transcript liefert awaitInput + zusaetzliches
        Language-Feld (service-owned)."""
        client = self._client()
        r = client.post(
            "/api/transcript",
            json={"sessionId": "yt08sid07c"},
            headers={"X-API-Key": "test-key"},
        )
        body = r.json()
        ai = body["awaitInput"]
        # URL muss drin sein
        names = {f.get("name") for f in ai["fields"]}
        assert "url" in names
        # Language-Feld (service-owned, optional)
        assert "language" in names, (
            f"Transkript-spezifisches language-Feld fehlt: {names}"
        )

    def test_comments_no_url_returns_await_input(self):
        """Auch /api/comments liefert awaitInput."""
        client = self._client()
        r = client.post(
            "/api/comments",
            json={"sessionId": "yt08sid07d"},
            headers={"X-API-Key": "test-key"},
        )
        body = r.json()
        assert "awaitInput" in body
        names = {f.get("name") for f in body["awaitInput"]["fields"]}
        assert "url" in names

    def test_download_no_url_returns_await_input(self):
        """Auch /api/download liefert awaitInput (mit audio_only etc.)."""
        client = self._client()
        r = client.post(
            "/api/download",
            json={"sessionId": "yt08sid07e"},
            headers={"X-API-Key": "test-key"},
        )
        body = r.json()
        assert "awaitInput" in body
        names = {f.get("name") for f in body["awaitInput"]["fields"]}
        assert "url" in names
        assert "audio_only" in names, (
            f"Download-spezifisches audio_only-Feld fehlt: {names}"
        )


# ---------------------------------------------------------------------------
# YT-05 (Phase 4): Write-Komplett-Garantie
# ---------------------------------------------------------------------------


class TestYT05_WriteCompletenessGate:
    """Spec YT-05 (Phase 4): Erst NACH erfolgreichem Write aller 3
    Resultset-Dateien darf ``headline.success=true`` zurueckgegeben
    werden.  Bei einem Write-Fehler (oder leerer Datei) muss
    ``success`` auf ``False`` flippen.
    """

    def test_success_true_when_all_three_writes_succeed(self, isolated_data_dir):
        sid = "yt05ok"
        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "OK"},
            request={"sessionId": sid, "url": "https://x"},
        )
        assert result.get("success") is True
        # Pflicht-Felder gesetzt
        assert result.get("jsonPath")
        assert result.get("mdPath")
        assert result.get("htmlPath")
        # _summary baut daraus headline.success
        s = build_summary("get-metadata", result, session_id=sid)
        assert s["headline"].get("success") is True

    def test_success_false_when_json_write_fails(self, isolated_data_dir, monkeypatch):
        """YT-05-Garantie: wenn json.write_text fehlschlaegt ->
        success=False + persistenceErrors + errorCode=PERSISTENCE_INCOMPLETE.

        Wir simulieren den Fehler durch Monkeypatching von
        ``Path.write_text`` -- das ist robuster als Filesystem-Tricks
        und testet genau die Stelle, an der YT-05 eingreift.
        """
        sid = "yt05failjson"
        real_write_text = Path.write_text

        def failing_write_text(self, *args, **kwargs):
            # Wir lassen nur md/html normal schreiben (sonst ist der
            # Test unleserlich), blockieren aber json -- so bleibt die
            # YT-05-Logik deterministisch testbar.
            name = self.name if isinstance(self, Path) else str(self)
            if name.endswith("result.json"):
                raise OSError(28, "No space left on device (simulated)")
            return real_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failing_write_text)

        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "Wird scheitern"},
            request={"sessionId": sid, "url": "https://x"},
        )
        assert result.get("success") is False, (
            f"success blieb True trotz Write-Fehler: {result!r}"
        )
        assert result.get("errorCode") == "PERSISTENCE_INCOMPLETE"
        assert result.get("persistenceErrors"), (
            "persistenceErrors fehlt bei Write-Fehler"
        )
        # JSON-Fehler ist im persistenceErrors-Trace
        joined = " ".join(result["persistenceErrors"])
        assert "json" in joined, (
            f"json-Fehler nicht in persistenceErrors: {result['persistenceErrors']!r}"
        )
        # headline in _summary
        s = build_summary("get-metadata", result, session_id=sid)
        assert s["headline"].get("success") is False, (
            f"headline.success sollte False sein: {s['headline']!r}"
        )

    def test_success_false_when_html_write_fails(self, isolated_data_dir, monkeypatch):
        """YT-05: html.write_text-Fehler flippt ebenfalls success."""
        sid = "yt05failhtml"
        real_write_text = Path.write_text

        def failing_write_text(self, *args, **kwargs):
            name = self.name if isinstance(self, Path) else str(self)
            if name.endswith("result.html"):
                raise OSError(13, "Permission denied (simulated)")
            return real_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failing_write_text)

        result = write_result(
            sid, "get-metadata",
            {"success": True, "title": "HTML fail"},
            request={"sessionId": sid, "url": "https://x"},
        )
        assert result.get("success") is False
        assert "html" in " ".join(result.get("persistenceErrors", []))

    def test_all_three_files_non_empty_after_success(
        self, isolated_data_dir
    ):
        """Spec YT-05: json/md/html jeweils >=1 Byte."""
        sid = "yt05nonempty"
        write_result(
            sid, "get-metadata",
            {"success": True, "title": "NonEmpty"},
            request={"sessionId": sid, "url": "https://x"},
        )
        rd = get_results_dir(sid)
        for ext in ("json", "md", "html"):
            size = (rd / f"{sid}.01result.{ext}").stat().st_size
            assert size >= 1, (
                f"{ext}-Datei <1 Byte (YT-05 verletzt): {size}"
            )


# ---------------------------------------------------------------------------
# YT-06: awaitInput ist service-owned
# ---------------------------------------------------------------------------


class TestYT06_AwaitInputServiceOwned:
    """Spec YT-06: Title, Beschreibung, URL-Label, Typ, Required-Flag,
    Placeholder kommen vollstaendig vom Service.  ME4-UI rendert nur.

    Hier verifizieren wir, dass die Werte in ``app.http_api._URL_FIELD``
    bzw. ``_await_input`` wirklich die vom Service gelieferten sind und
    nicht von einem UI-Hardcode ueberschrieben werden.
    """

    def test_url_field_defined_in_service_module(self):
        from app import http_api
        fields = http_api._URL_FIELD
        assert fields, "_URL_FIELD fehlt in app/http_api.py"
        url = fields[0]
        assert url["name"] == "url"
        assert url["type"] == "url"
        assert url["required"] is True
        assert url["placeholder"]

    def test_metadata_await_input_envelope_shape(self):
        """Der ``_await_input``-Helper produziert die kanonische Form."""
        from app.http_api import _await_input
        envelope = _await_input(
            "Titel",
            "Beschreibung",
            [{"name": "url", "label": "YouTube URL", "type": "url",
              "required": True, "placeholder": "https://..."}],
        )
        assert set(envelope.keys()) == {"awaitInput"}
        ai = envelope["awaitInput"]
        assert ai["title"] == "Titel"
        assert ai["description"] == "Beschreibung"
        assert ai["fields"][0]["name"] == "url"
