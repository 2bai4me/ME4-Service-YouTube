## Was ändert sich?

<!-- 1-3 Bullet-Points: WAS? -->

## Motivation

<!-- WARUM? Welches Issue? `Closes #123` / `Refs #456` -->

## Wie wurde getestet?

- [ ] `pytest` ist grün
- [ ] `pytest --cov=app --cov-fail-under=80` ist grün (falls Coverage-Gate aktiv)
- [ ] Manuelle Smoke-Tests gegen Live-Service durchgeführt
- [ ] Keine neuen Netzwerk-Calls in Tests (außer gemockt)

## Pilot-Kontext

<!-- Pflicht wenn Änderung Service-Vertrag, Manifest-Schema, oder Pilot-Standard berührt -->

- [ ] Ändert das `/api/manifest`-Schema → `docs/INTEGRATION.md` aktualisiert
- [ ] Fügt neuen MCP-Tool hinzu → `FUNCTIONS.md` + `SERVICE.md` aktualisiert
- [ ] Ändert Pipeline-Stages → `FUNCTIONS.md` aktualisiert
- [ ] Ändert Boot-Reihenfolge → `SERVICE_START.md` aktualisiert
- [ ] Keine der oben genannten Änderungen

## Checkliste

- [ ] Conventional-Commits-Message im PR-Titel verwendet
- [ ] `CHANGELOG.md`-Eintrag unter `[Unreleased]` oder neue Release-Version
- [ ] Keine Breaking Changes ODER `BREAKING CHANGE:` im Footer + `BREAKING:` in CHANGELOG
- [ ] Alle Pflicht-Files vorhanden (Pilot 0.5.2: README, LICENSE, CHANGELOG, AGENT, SERVICE, FUNCTIONS, …)
- [ ] `.env.example` aktualisiert wenn neue Env-Vars
- [ ] Keine Secrets in Diffs (auch nicht in `.env.example`)
- [ ] Keine neuen hartcodierten Werte (URLs, Ports, IPs, Service-IDs)
- [ ] `python D:\Entwicklung\scripts\audit-md-links.py .` lokal geprüft
- [ ] Pilot-0.5-Pre-Commit-Hook lokal geprüft (`bash .git/hooks/pre-commit`)

## Verwandte Issues / PRs

<!-- `Closes #…`, `Refs #…`, `Blocked by #…` -->