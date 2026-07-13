# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

