# Security Policy

> Verbindlich für alle, die Sicherheitslücken in diesem Projekt melden oder beheben wollen.

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

Ältere Versionen erhalten keine Sicherheits-Updates. Wir empfehlen dringend
ein Upgrade auf die aktuellste stabile Version.

## Reporting a Vulnerability

**Bitte KEINE Sicherheitslücken als öffentliches GitHub-Issue melden.**

Stattdessen:

1. **E-Mail** an `security@me4.local` (verschlüsselt, PGP-Key auf Anfrage)
   - Subject: `[SECURITY] ME4-S-youtube <Kurzbeschreibung>`
   - Body: Reproduktionsschritte, betroffene Version, Impact-Einschätzung
2. **Erwartete Antwortzeit:** innerhalb von 72 Stunden (Bestätigung des Empfangs)
3. **Status-Updates:** alle 7 Tage bis zur Behebung
4. **Koordinierter Disclosure:** Wir koordinieren den Veröffentlichungszeitpunkt
   mit dir. Default-Frist: 90 Tage nach Bestätigung.

### Was du im Report enthalten solltest

- Beschreibung der Schwachstelle (Konzept, Impact, betroffene Komponenten)
- Schritte zur Reproduktion (Proof-of-Concept-Code willkommen)
- Betroffene Version(en) und Commit-Hashes
- Deine Einschätzung von Schweregrad und Exploit-Reife
- Kontakt für Rückfragen

### Was du NICHT tun solltest

- Keine öffentlichen Issues, Discussions oder Tweets vor koordinierter Veröffentlichung
- Keine destruktiven Tests gegen fremde Instanzen (nur gegen deine eigene)
- Keine Ausnutzung der Lücke über die Reproduktion hinaus

## Disclosure Process

1. **Eingang:** Bestätigung innerhalb von 72h
2. **Triage:** Severity-Einschätzung (CVSS v3.1) und Reproduktion
3. **Fix-Entwicklung:** Patch in privatem Branch, Tests, Code-Review
4. **Koordinierter Release:** Sicherheits-Release + CVE-Beantragung (CNA: GitHub)
5. **Public Disclosure:** Security Advisory auf GitHub + CHANGELOG-Eintrag mit `SECURITY:`-Präfix

## Severity-Modell (vereinfacht nach CVSS v3.1)

| Severity | Beispiel | Reaktionszeit |
|---|---|---|
| **Critical** (9.0–10.0) | Remote Code Execution, Auth-Bypass | sofort (Hotfix) |
| **High** (7.0–8.9) | Privilege Escalation, Daten-Exfiltration | 7 Tage |
| **Medium** (4.0–6.9) | XSS, CSRF auf geschützten Routen | 30 Tage |
| **Low** (0.1–3.9) | Information Disclosure ohne Impact | 90 Tage |

## Security-Best-Practices für Nutzer

- **API-Key (`API_KEY` in `.env`):** Niemals committen, immer via Secret-Manager
- **Dev-Mode (`API_KEY=""`):** NIEMALS in Production deployen — Auth ist komplett aus
- **TLS:** Service läuft HTTP-only — vor Production unbedingt hinter Reverse-Proxy mit TLS
- **Updates:** Aktuelle Version verwenden, Sicherheits-Releases zeitnah einspielen
- **Logs:** Vor dem Teilen von `service.log` sensible Daten redigieren

## Acknowledgments

Wir bedanken uns bei allen Sicherheitsforschern, die verantwortungsvoll
Schwachstellen melden. Mit deiner Einwilligung wirst du in der Security-Advisory
genannt.

## Out of Scope

- Social Engineering gegen Maintainer
- Phishing-Kampagnen
- Denial-of-Service gegen unsere Infrastruktur
- Schwachstellen in Abhängigkeiten, die bereits upstream gemeldet/gefixt sind
  (bitte direkt beim Upstream-Projekt melden)

Vielen Dank für deine Mitarbeit an der Sicherheit dieses Projekts.