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

