# Contributing to ME4-YouTube

> **Vielen Dank** für dein Interesse, zu diesem Projekt beizutragen. Diese Anleitung hilft dir, einen reibungslosen PR-Prozess zu durchlaufen.

## Code of Conduct

Dieses Projekt folgt dem [Contributor Covenant](https://www.contributor-covenant.org/de/version/2/1/code_of_conduct/).
Mit deiner Teilnahme verpflichtest du dich, dessen Regeln einzuhalten. Verstöße bitte an `conduct@me4.local` melden.

## Quick Links

- [Issue Tracker](https://github.com/2bai4me/ME4-S-youtube/issues)
- [Pull Requests](https://github.com/2bai4me/ME4-S-youtube/pulls)
- [Discussions](https://github.com/2bai4me/ME4-S-youtube/discussions)
- [`AGENT.md`](AGENT.md) — Briefing für neue Mitstreiter
- [`SERVICE.md`](SERVICE.md) — Schnittstellen-Spezifikation
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Design-Dokumentation
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — UI↔Service-Vertrag

## Pre-Commit-Hook (lokal)

Das Repo enthält einen **lokalen** Pre-Commit-Hook unter `scripts/git-hooks/pre-commit`,
der dieselben Regeln prüft wie der GitHub-Actions-Workflow `.github/workflows/docs-lint.yml`.

**Install (einmalig nach Clone):**
```bash
cp scripts/git-hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

**Was er prüft:**
- `CHANGELOG.md` hat einen `[Unreleased]`-Block
- `README.md` hat einen Badge-Block in den ersten 10 Zeilen
- Alle internen Markdown-Links sind auflösbar (via `D:\Entwicklung\scripts\audit-md-links.py`)
- Alle Pilot-0.5.2-Pflicht-Files sind vorhanden
- `.env.example` enthält keine verdächtigen Secret-artigen Werte
- **Baustein-spezifisch (UI):** keine service-spezifische Logik in `src/` (Golden Rule)

**Skip (NOT recommended):**
```bash
git commit --no-verify
```

## Development Setup

```bash
# 1. Repo klonen
git clone https://github.com/2bai4me/ME4-S-youtube.git
cd ME4-S-youtube

# 2. Venv anlegen
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# 3. Dependencies installieren
pip install -r requirements.txt
pip install -r requirements-dev.txt    # falls vorhanden

# 4. Pre-Commit-Hook installieren
pip install pre-commit
pre-commit install
# ODER (Pilot 0.5.6 lokaler Spiegel des CI-Guards):
cp scripts/git-hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# 5. Konfiguration
cp .env.example .env
# API_KEY leer lassen für Dev-Mode, sonst setzen

# 6. Tests laufen lassen (Baseline)
pytest

# 7. Service starten
python main.py --no-browser
```

## Pull-Request-Prozess

### 1. Issue zuerst

Für **größere Änderungen** (Refactoring, neue Features, API-Änderungen)
bitte **vorher ein Issue** erstellen und das Design absprechen.
Für triviale Fixes (Tippfehler, off-by-one, klare Bugs) direkt PR.

### 2. Branch-Naming

```
feat/<kurzname>           Neue Features
fix/<kurzname>            Bugfixes
docs/<kurzname>           Reine Doku-Änderungen
chore/<kurzname>          Tooling, CI, Refactoring ohne Verhaltensänderung
test/<kurzname>           Test-Erweiterungen
refactor/<kurzname>       Code-Refactoring ohne Feature-Änderung
```

### 3. Commit-Messages

Folgen [Conventional Commits 1.0](https://www.conventionalcommits.org/de/v1.0.0/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`, `revert`

**Breaking Changes** MÜSSEN im Footer mit `BREAKING CHANGE: <beschreibung>` markiert
werden UND im `CHANGELOG.md` unter `[Unreleased]` mit `### Changed` + `BREAKING:`-Präfix.

**Beispiele:**
```
feat(metadata): add support for video chapters in response

Adds chapters[] array to /api/metadata response when YouTube
video has chapter markers. Backwards-compatible (existing
clients ignore the new field).

Closes #42
```

```
fix(auth): prevent timing attack on API key comparison

BREAKING CHANGE: Auth-Vergleich nutzt jetzt hmac.compare_digest()
statt ==. Verhalten identisch, aber Clients mit eigenem Timing-
sensitiven Auth-Code MÜSSEN ihre Tests anpassen.
```

### 4. Code-Qualität

Vor jedem Commit:

- [ ] `pytest` läuft grün (alle Tests, keine Netzwerk-Calls außer in gemockten Tests)
- [ ] `pytest --cov=app --cov-report=term-missing` zeigt ≥80% Coverage
- [ ] Keine `print()`-Statements (nur `logger.info/warning/error`)
- [ ] Keine hartcodierten Secrets, IPs, Ports
- [ ] Type Hints auf allen Public Functions (PEP 484)
- [ ] Docstrings auf allen Public Functions (PEP 257)
- [ ] Neue Public Functions in `FUNCTIONS.md` dokumentiert
- [ ] Neue Config-Variablen in `.env.example` ergänzt (mit `# REQUIRED in production` wenn nötig)

### 5. Doku-Synchronisation

Wenn deine Änderung eine der folgenden berührt, MUSS die zugehörige Doku im selben PR aktualisiert werden:

| Code-Änderung | Doku-Datei |
|---|---|
| Neuer MCP-Tool | `README.md` (Schnittstellen-Tabelle) + `FUNCTIONS.md` + `/api/manifest` |
| Neue Pipeline-Stage | `FUNCTIONS.md` + `/api/manifest.functions[]` |
| Neue Config-Variable | `.env.example` + `SERVICE.md` (Config-Tabelle) + `README.md` |
| Boot-Reihenfolge geändert | `SERVICE_START.md` + ggf. `ARCHITECTURE.md` |
| Auth-Verhalten geändert | `SECURITY.md` + `SERVICE.md` (Compliance) |
| Breaking API-Change | `CHANGELOG.md` mit `BREAKING:` + `docs/INTEGRATION.md` (falls UI-relevant) |

### 6. Review

- Mindestens **1 Approval** von einem Maintainer
- Alle CI-Checks grün
- Keine unaufgelösten Review-Kommentare
- Bei Breaking Changes: zusätzliche Approval von einem zweiten Maintainer

### 7. Merge

- **Squash-and-Merge** für Feature-Branches (saubere History)
- **Merge-Commit** für Release-Branches
- Nach Merge: Branch löschen

## Style-Guide

### Python

- [PEP 8](https://peps.python.org/pep-0008/) als Basis
- [PEP 257](https://peps.python.org/pep-0257/) für Docstrings (Google-Style)
- [PEP 484](https://peps.python.org/pep-0484/) für Type Hints
- `ruff` als Linter (siehe `.ruff_cache/`)
- Imports: `stdlib`, dann `third-party`, dann `local`, je alphabetisch
  - Automatisch via `ruff check --select I --fix`

### Markdown

- Files in `kebab-case.md` (außer `README.md`, `LICENSE`, `AGENT.md`, `CHANGELOG.md`)
- Heading-Hierarchie: H1 → H2 → H3, **keine** Sprünge (H1 → H3 vermeiden)
- Code-Blöcke mit Sprache: ` ```python `, ` ```bash `, ` ```json `, **nie** ` ``` `
- Links: bevorzugt relative (`./docs/foo.md`) statt absolute (`D:/Entwicklung/...`)

### Config & .env

- Sektion-Header per Kommentar: `# === Auth ===`, `# === Ports ===`
- Production-mandatory Vars: Kommentar `# REQUIRED in production` darunter
- **Niemals echte Werte** in `.env.example`, auch nicht für Beispiele

## Testing

### Was testen?

- **Unit-Tests** für alle nicht-trivialen Funktionen
- **Integration-Tests** für zusammengesetzte Flows (Orchestrator, Worker)
- **Property-Based-Tests** (hypothesis) für Parser/Validatoren
- **Keine** Netzwerk-Calls in Tests (yt-dlp-Output immer mocken)

### Wie?

```bash
pytest                                    # alle Tests
pytest tests/test_extractor.py            # einzelne Datei
pytest -k "test_metadata"                 # nach Name filtern
pytest --cov=app --cov-report=term-missing # mit Coverage
pytest --cov=app --cov-fail-under=80      # Coverage-Gate
```

## Bug-Reports

Bitte das **Bug-Report-Issue-Template** verwenden (`.github/ISSUE_TEMPLATE/bug_report.md`).
Wenn du keinen GitHub-Account hast: E-Mail an `bugs@me4.local`.

## Feature-Requests

Bitte das **Feature-Request-Issue-Template** verwenden (`.github/ISSUE_TEMPLATE/feature_request.md`).
Für Design-Diskussionen vor dem Issue: [Discussions](https://github.com/2bai4me/ME4-S-youtube/discussions).

## Lizenz

Mit deinem Beitrag akzeptierst du die [MIT-Lizenz](LICENSE) dieses Projekts.
Alle Beiträge stehen unter derselben Lizenz.

## Fragen?

- **Allgemein:** [Discussions](https://github.com/2bai4me/ME4-S-youtube/discussions)
- **Sicherheit:** siehe [SECURITY.md](SECURITY.md)
- **Code-of-Conduct-Verstöße:** `conduct@me4.local`

Danke, dass du hilfst, dieses Projekt besser zu machen. 🚀