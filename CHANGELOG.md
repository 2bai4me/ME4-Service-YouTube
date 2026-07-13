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
