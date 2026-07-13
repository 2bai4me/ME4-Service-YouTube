# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.4] - 2026-07-13

### Fixed
- `next_function_index` parser was overwriting `.01result.*` on every call because
  it tested tokens with `isdigit()` that contained letters (`"abc123"`,
  `"01result"`). New parser uses regex
  `^[sid]\.(\d{2})result\.(json|md|html)$`, counts three file-views of the same
  result as ONE sequence, and returns the next `NN` as a 2-digit string.
  Regression test in `tests/test_seq_parser.py` covers the core finding
  (two calls → `.01` and `.02`, no overwrite). Service version 1.0.0 → 1.0.4.
  See PR #2 for the full PR-body / conversation (F-05 fix per BPSpec
  `.spec/offen/me4-ui-service-owned-interaction-v1-audit-2026-07-12.md`).

### Notes
- Full change-log entry retained in `[Unreleased]` below — this release section
  records the shipped item plus its PR pointer.

## [1.0.5] - 2026-07-13

### Fixed
- `_summary` directory fields (`dirAbsolute`, `filesSavedTo`) now point at the
  canonical `<session>/results/` directory instead of the per-function subdir.
  New `resultsDir` legacy alias (identical to `dirAbsolute`), optional
  `sessionDir`, mandatory `files[]` filtered to the current resultset
  (`<sid>.<NN>result.{ext}`), explicit `jsonPath` / `mdPath` / `htmlPath`,
  optional `listingError`. Implementation in new `app/response_contract.py`
  (no FastAPI import, isolated testable); `app/http_api.py` reduced to a thin
  wrapper. Helper `to_windows_url(Path)` added in `app/session_store.py`.
  Three new tests in `tests/test_dir_contract.py` (21 asserts).
- `write_result` migrated to the canonical
  `<session>/results/<sid>.<NN>result.{ext}` layout (was the per-function
  subdir `<session>/<NN-function>/`). Now uses `next_function_index(session_id)`
  for the sequence number and annotates `result["jsonPath"|"mdPath"|"htmlPath"]`
  so `_summary` extracts the current NN robustly from the path field (not from
  the parser return value, which yields `max+1`). `get_function_dir` is now
  deprecated. Three sequential regression tests renamed per user spec and now
  exercise the real `write_result` path instead of `_touch` simulation.
  Service version 1.0.4 → 1.0.5. See PR #3 for the full PR-body /
  conversation (F-03 / F-04 / B-2 fixes per BPSpec).

### Added
- **New:** `services/me4-youtube.service.json` — 5th version-mirror location per
  AD-6 (`me4-versioning-rule`, see BPSpec
  `.spec/offen/me4-ui-service-owned-interaction-v1-audit-2026-07-12.md` §
  „Version-Bump-Spiegelorte“). Carries `"version": "1.0.5"` in sync with
  `pyproject.toml`, `app/__init__.py` (`__version__`) and `app/config.py`
  (`settings.service_version`).

### Notes
- Full change-log entries retained in `[Unreleased]` below — this release section
  records the shipped items plus their PR pointer (deliberate safer choice:
  original `[Unreleased]` texts are NOT removed to avoid double-maintenance
  risk; the released sections above are the canonical shipped-history pointers).

## [1.0.6] - 2026-07-13

### Fixed
- `fix(service): YT-05 write-result completeness gate (Phase 4)` —
  `write_result` schrieb bisher die drei Resultset-Dateien
  (``<sid>.<NN>result.{json,md,html}``) ohne Erfolgs-Gate: wenn ein
  Write fehlschlug (z.B. ``OSError`` weil Disk voll oder Path blockiert),
  bubblte die Exception bis zum HTTP-Endpoint hoch und produzierte einen
  HTTP-500, obwohl der Upstream-``success``-Wert ``true`` war.  Phase-4-
  Fix: jeder der drei ``Path.write_text``-Calls ist jetzt in einen
  ``try/except OSError``-Block eingewickelt, die Ergebnisse werden in
  ``write_errors`` gesammelt.  Nach dem Write-Block wird per
  ``Path.stat().st_size >= 1`` geprueft, dass alle drei Dateien
  tatsaechlich nicht-leer sind (Spec YT-05: ``≥1 Byte``).  Bei Fehlern
  wird ``result["success"]`` auf ``False`` gesetzt, ein expliziter
  ``errorCode="PERSISTENCE_INCOMPLETE"`` plus ``persistenceErrors``
  angehaengt und der ``error``-String erweitert.  Annotation der
  ``jsonPath``/``mdPath``/``htmlPath``-Felder erfolgt weiterhin, damit
  die UI auch im Fehlerfall die intendierten Pfade rendern kann.
  ``update_session_notes`` wird im ``try/except`` ausgefuehrt (best-
  effort), damit ein Notes-Fehler nie den eigentlichen Write-Pfad
  blockiert.  Service-Version 1.0.5 → 1.0.6.

### Added
- `tests/test_phase4_persistence.py` — YT-08 + YT-05 + YT-06 Contract-
  und Persistenztests (22 Cases, alle gruen):
  * **YT-08-1** WORK_DIR/session/<sid>/results wird erzeugt
  * **YT-08-2** erster Aufruf schreibt ``.01result.{json,md,html}`` (alle >=1 Byte)
  * **YT-08-3** zweiter Aufruf schreibt ``.02result.*`` und ueberschreibt ``.01`` NICHT
  * **YT-08-4** ``dirAbsolute == filesSavedTo == resultsDir``
  * **YT-08-5** ``jsonPath``/``mdPath``/``htmlPath`` liegen INNERHALB ``dirAbsolute``
  * **YT-08-6** ``files[]`` entspricht 1:1 dem Filesystem-Listing von ``dirAbsolute``
  * **YT-08-7** fehlende URL liefert korrektes ``awaitInput`` (Title, Description, URL-Label, Typ, Required, Placeholder) — inkl. ``/api/metadata``, ``/api/transcript``, ``/api/comments``, ``/api/download``
  * **YT-05** Write-Komplett-Garantie: success=true nur wenn alle 3 Writes OK + Dateien non-empty; Write-Fehler flippen ``success`` auf ``false`` mit ``errorCode="PERSISTENCE_INCOMPLETE"``
  * **YT-06** ``awaitInput`` ist service-owned (URL-Feld in ``app/http_api._URL_FIELD``; envelope-Form durch ``_await_input``-Helper)

### Notes
- Verifikation: ``pytest tests/test_phase4_persistence.py -v`` → 22 passed.
- Vollstaendige Suite: ``pytest tests/`` → 122 passed, 2 pre-existing failed
  (``test_http_api.py::test_manifest`` + ``test_zmq_service.py::test_manifest_contains_loadbalancer``
  erwarten ``data["service_id"]`` auf Top-Level, die aktuelle
  ``/api/manifest``-Implementierung liefert es unter
  ``data["service_bus_manifest"]["service_id"]`` -- nicht in Phase-4-Scope,
  vor Phase 2.2 manifest-refactor bereits divergent).

## [1.0.7] - 2026-07-13

### Added
- **Pfad-Translation WSL/Linux -> Windows-UI**: Neue Helper-Funktion
  ``app/path_utils.to_platform_path(p, *, windows=None)`` uebersetzt
  Pfade, die mit ``/mnt/<drive>/`` beginnen, in die Windows-Form
  ``<DRIVE>:\<rest-mit-Backslashes>``, sobald das neue Setting
  ``settings.windows_path_translation=True`` gesetzt ist (oder der
  explizite ``windows=True``-Override greift).  Pfade ohne
  ``/mnt/<drive>/``-Prefix (z.B. ``/tmp/...``) bleiben unveraendert in
  POSIX-Form -- das Windows-Browser-UI kann sie ohnehin nicht oeffnen,
  eine Doppel-Anzeige wuerde nur verwirren.
- **Neue Setting ``windows_path_translation``** in ``app/config.py``
  (Default: ``False``, Linux-natives Format).  Aktivierbar per
  Env-Variable ``WINDOWS_PATH_TRANSLATION=true`` oder in ``.env``.  Die
  Translation greift fuer alle 6 Pfad-Felder des Response-Contracts:
  ``dirAbsolute``, ``filesSavedTo``, ``resultsDir``, ``sessionDir``,
  ``jsonPath``, ``mdPath``, ``htmlPath``.
- **``files[]``-Erweiterung um ``path`` + ``openUrl``**: Jeder Eintrag
  in ``files[]`` hat jetzt zusaetzlich zu ``{name, size, mtimeMs}``
  ein ``path``-Feld (gleiche Translation wie ``dirAbsolute``, z.B.
  ``D:\DEV\wt-me4-yt-paths-open\data\sessions\<sid>\results\
  <sid>.<NN>result.html``) und ein ``openUrl``-Feld
  (``file:///D:/DEV/...``-URI fuer direkten Browser-Open).  Damit kann
  die UI einen anklickbaren "Oeffnen"-Button rendern.
- **Neuer Helper ``to_file_uri(path_str)``** in ``app/path_utils.py``
  konvertiert einen beliebigen Pfad-String (POSIX oder Windows-Form)
  in eine gueltige ``file://``-URI (drei Slashes fuer absolute Windows-
  Pfade mit Drive-Letter, zwei Slashes fuer absolute POSIX-Pfade).
- **Neue Test-Datei ``tests/test_phase4b_paths.py``** (12 Tests,
  3 Klassen): Translation an/aus, WSL- vs non-WSL-Pfade,
  Nested-Subdirs, plus Vertragspflicht-Tests fuer ``files[].path`` /
  ``files[].openUrl``.

### Changed
- **Pfad-Generierung nutzt jetzt den Helper**: ``app/session_store.to_windows_url``
  ist jetzt ein Backward-Compat-Shim, der an ``to_platform_path``
  delegiert (mit ``windows=None``, also Setting-getrieben).  Der bisherige
  ``return Path(path).resolve().as_posix()``-Body wurde ersetzt -- damit
  greift die Translation auch fuer den ``result.jsonPath`` /
  ``result.mdPath`` / ``result.htmlPath``-Annotator in ``write_result``
  (Phase-4-Write-Pfad), ohne dass der Annotator geaendert werden musste.
- **``app/response_contract.build_summary``** ruft jetzt ``to_platform_path``
  statt ``to_windows_url`` fuer die 6 Top-Level-Pfad-Felder (semantisch
  identisch via Setting, aber klarer im Code-Review).
- **``app/response_contract.list_resultset_files``** setzt jetzt
  zusaetzlich ``path`` und ``openUrl`` pro File-Eintrag.
- **Version-Spiegel**: 5 Spiegelorte + ``tests/test_config.py``
  konsistent auf ``1.0.7`` (pyproject.toml, app/__init__.py,
  app/config.py, services/me4-youtube.service.json, CHANGELOG.md,
  test_config.test_defaults).

### Notes
- Verifikation: ``pytest tests/`` -> 134 passed (122 Baseline + 12 neu),
  2 pre-existing failed (manifest-tests, dokumentiert in 1.0.6-Notes).
- Out-of-Scope-Reminder:
  * ``data_dir`` -> ``WORK_DIR``-Migration (Spec E-3, separates Issue;
    aktuell schreibt der Service nach ``./data/sessions/`` statt
    ``./work/sessions/``).
  * UI-04 Strict Validation + "Oeffnen"-Button-Rendering (UI-Code,
    Phase 5; die neuen Felder sind transportiert, aber die UI muss sie
    noch rendern).
- Vollstaendige Suite inkl. Phase-4-Regression-Check:
  ``pytest tests/ -v 2>&1 | tail -40``.

## [Unreleased]

### Fixed
- `fix(service): correct next_function_index parser (F-05)` —
  Parser überschrieb bei jedem Aufruf `.01result.*`, weil er mit
  `isdigit()` auf Tokens prüfte, die Buchstaben enthalten
  (`"abc123"` und `"01result"`).  Neuer Parser verwendet Regex
  `^[sid]\.(\d{2})result\.(json|md|html)$`, zählt drei
  Dateiansichten desselben Ergebnisses als EINE Sequenz und gibt
  das nächste `NN` als 2-stelligen String zurück.  Regressionstest
  in `tests/test_seq_parser.py` deckt den Kern-Befund ab (zwei
  Aufrufe → `.01` und `.02`, keine Überschreibung).  Service-Version
  1.0.0 → 1.0.4.
- `fix(service): correct _summary directory fields (Phase 2 / F-03, F-04)` —
  `_summary` lieferte bisher `filesSavedTo` aus `result._dir`, was auf den
  Per-Function-Subdir (`<session>/<NN-function>/`) zeigte — nicht auf das
  kanonische Results-Verzeichnis `<session>/results/`.  Vertrags-Korrektur:
    * `dirAbsolute` und `filesSavedTo` zeigen jetzt beide auf
      `<session>/results/` (Windows-URL-Form: absolut, forward-slashes,
      kein `file://`).
    * Neuer Legacy-Alias `resultsDir` (identisch zu `dirAbsolute`) plus
      optionales `sessionDir` für UI-Tests.
    * Neues Pflicht-Feld `files[]` mit `{name, size, mtimeMs}`, gefiltert
      per Regex `^[sid]\.(\d{2})result\.(json|md|html)$` auf das aktuelle
      Resultset (`<sid>.<NN>result.{ext}`).  `Notes.md`, Verzeichnisse
      und Vorgänger-Resultsets werden ausgeschlossen.
    * Neue Felder `jsonPath` / `mdPath` / `htmlPath` als absolute Pfade
      zu den drei konkreten Dateien des aktuellen Resultsets.
    * Neues Feld `listingError` (optional, `None` bei OK).
  Implementierung in neuem Modul `app/response_contract.py` (kein
  FastAPI-Import, isoliert testbar).  `app/http_api.py` hält nur noch
  einen dünnen Wrapper.  Neuer Helper `to_windows_url(Path)` in
  `app/session_store.py` für die Pfad-Konvertierung.  Drei neue
  pytest-Tests in `tests/test_dir_contract.py` (21 Asserts), inkl.
  Regressionstest „sequenzielle Resultsets überschreiben sich nicht".
  NB-3-Konformität: `next_function_index` wird nur als Fallback für die
  Pfad-Felder benutzt; sein String-Rückgabewert wird nie
  re-formatiert (`f"{nn:02d}"` würde „0105" liefern).
  Service-Version 1.0.4 → 1.0.5.
- `fix(service): migrate write_result to canonical resultsets (Phase 2 B-2)` —
  `write_result` schrieb bisher in den Per-Function-Subdir
  `<session>/<NN-function>/` und annotierte nur `result["_dir"]`.  Damit
  zeigten die Phase-2-Vertragsfelder (`jsonPath`/`mdPath`/`htmlPath`,
  `files[]`, `dirAbsolute`) auf nicht-existente Dateien.  Cross-Review-
  Fix (B-2): Migration auf das kanonische Resultset-Layout
  `<session>/results/<sid>.<NN>result.{ext}`.  `write_result` nutzt jetzt
  `next_function_index(session_id)` für die Sequenznummer und annotiert
  `result["jsonPath"|"mdPath"|"htmlPath"]`, damit `_summary` das aktuelle
  NN robust aus dem Path-Feld extrahieren kann (statt aus dem
  Parser-Rückgabewert, der `max+1` liefert).  `get_function_dir` ist
  jetzt deprecated (kein Aufrufer mehr in `app/`/`tests/`).
  Drei Tests umbenannt auf User-Vorgabe
  (`test_dirabsolute_points_to_results`, `test_files_list_filters_to_resultset`,
  `test_sequential_results_no_overwrite`).  Sequenzielle Regression-Tests
  exerzieren jetzt den echten `write_result`-Pfad statt `_touch`-Simulation.

