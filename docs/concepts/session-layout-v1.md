# Concept: Session-Layout v1 (singular `data/session/<sid>/`)

> Status: **active** since **ME4-S-youtube v1.1.0** (2026-07-15).
> Spec source: `me4-ui-service-owned-interaction-v1-audit-2026-07-12.md`
> § AD-8 (canonical on-disk layout) and § Phase 4 (Migration Story).

## 1. TL;DR

The service writes per-session data under **one singular directory**:

    <DATA_DIR>/session/<safe_sid>/

(where `<DATA_DIR>` is `settings.data_dir`, default `./data`). The
pre-v1.1.0 plural form `data/sessions/<sid>/` is auto-migrated on
first start and then ignored; reads still accept it for one minor
release so the migration is non-disruptive.

This doc exists because the on-disk shape was confusing — the
`data/sessions/<sid>/results/` layout combined with the per-result
sequence number (`<sid>.<NN>result.*`) looked like "all sessions in
one folder" to a casual user, even though `.01` / `.02` / `.03` are
**stages of one session**, not three different sessions. Section 4
explains this in detail.

## 2. Canonical directory layout (spec-aligned)

```
<DATA_DIR>/                                   # settings.data_dir
└── session/                                  # singular! (was: sessions/)
    └── <safe_sid>/                           # sanitised session id
        ├── Notes.md                          # append-only log,
        │                                     #   line 1 = "# Session <safe_sid>"
        └── results/                          # resultset directory
            ├── <safe_sid>.01result.json
            ├── <safe_sid>.01result.md
            ├── <safe_sid>.01result.html
            ├── <safe_sid>.02result.json
            ├── <safe_sid>.02result.md
            └── <safe_sid>.02result.html
```

### Why singular `session/` (not `sessions/`)

The spec (AD-8 / Phase 4) and the ME4-UI response-validator Stage 3
both expect the path to **end with** `/work/session/<sid>/results`.
A trailing `sessions/` would trigger:

    ⚠️ does not end with the canonical /work/session/<sid>/results

on **every** reply, which is what the user was seeing. The fix is
the singular form; the migration moves the on-disk data in place.

### Why per-call artefacts are siblings (not subdirectories)

Phase 2 / F-03 + F-04 flattened the layout from `<sid>/<NN-func>/…`
to `<sid>/results/<sid>.<NN>result.<ext>`. Three file-views of the
same logical result (`.json`, `.md`, `.html`) count as **one**
sequence. The next call gets `<NN> + 1`. This is enforced by
`next_function_index(session_id)` in `app/session_store.py`.

### Why `Notes.md` lives in the session root, not in `results/`

`Notes.md` is a per-session log, not a per-result artefact. Keeping
it in the root makes it easy to open and append to without having to
re-scan `results/`. The append is idempotent: if `Notes.md` does not
exist yet, the first line is always `# Session <safe_sid>`.

## 3. Migration story (C3 in the contract)

On the first service start after the upgrade, `main.py` invokes
`scripts/migrate_session_layout.py --force`. The script:

1. **Detects** `data/sessions/` (plural, pre-v1.1.0).
2. **Backs up** the entire `data/sessions/` tree to
   `data/sessions.legacy-<UTC-ts>/` first. Only after the backup
   succeeds do per-session moves start.
3. **Moves** each `<sid>/` from `data/sessions/<sid>/` to
   `data/session/<sid>/` atomically (`os.replace` — observable to
   other processes as either fully-old or fully-new, no half-state).
4. **Skips** a session if the canonical target already exists
   (idempotency — running the script twice in a row is a no-op the
   second time).
5. **Renames** empty pre-1.0.5 leftovers: `data/work/` and any
   `data/work.backup-*` get a `.legacy-empty-<ts>/` suffix instead
   of being deleted. If `data/work/session/<sid>/` is **non-empty**,
   the script does **not** touch it and bumps the exit code to 2
   (operator review).
6. **Writes** a JSON report to stdout **and** to
   `data/migration/<UTC-ts>.log`. Exit codes:
   * `0` = clean (no work needed OR all moves succeeded)
   * `1` = partial (some moves failed; see report)
   * `2` = needs operator review (non-empty `work/` detected)

Migration is **best-effort**: it never blocks the service start, but
the log line is always emitted so the operator notices.

### CLI

    # Safe default: simulate the move (no files touched)
    python scripts/migrate_session_layout.py --dry-run

    # Actually move
    python scripts/migrate_session_layout.py --force

    # Override data dir
    python scripts/migrate_session_layout.py --force --data-dir /var/lib/me4-youtube

## 4. FAQ — "Why are there `.01/.02/.03` files in one folder?"

**Q**: I see `data/sessions/a1ed6c59/results/` with files
`a1ed6c59.01result.json`, `a1ed6c59.02result.json`, … Are these three
different sessions accidentally merged into one folder?

**A**: No. They are three **stages of one session** (the session id
is `a1ed6c59`). The number after the dot is the per-session call
sequence. The first call to the service for this session produced
`.01`; a second call produced `.02`; a third produced `.03`. After
the v1.1.0 migration the folder is renamed to
`data/session/a1ed6c59/results/`.

The three files with the same `<NN>` (`.01result.json`,
`.01result.md`, `.01result.html`) are **three views of the SAME
logical result**, not three results:

| File                    | Purpose                                              |
|-------------------------|------------------------------------------------------|
| `<sid>.<NN>result.json` | Raw data (what the upstream function returned)      |
| `<sid>.<NN>result.md`   | Human-readable Markdown summary                      |
| `<sid>.<NN>result.html` | Standalone HTML (with embedded CSS, opens in browser)|

`next_function_index(session_id)` counts the three views as **one**
sequence, so the second call gets `<NN> + 1` (= `02`), not `04`. The
`Notes.md` at the session root links to all three views of the
current result and lists which call produced which.

**Q**: So `a1ed6c59` and `021297a1` are two different sessions, yes?

**A**: Yes. Each is its own top-level folder under
`data/session/`. Within each folder, `.01` / `.02` / `.03` are
sequential calls of the **same** session. The directory tree
(per-session folder) and the filename sequence (per-call within a
session) are two different axes — the on-disk shape makes them
explicit:

    data/session/a1ed6c59/    ← session 1 (folder)
    data/session/021297a1/   ← session 2 (different folder)
    data/session/b9141c8c/   ← session 3 (different folder)
    data/session/c07921ba/   ← session 4
    data/session/pollytest01/  ← session 5
    data/session/probe002/   ← session 6

**Q**: Why not put each call in its own subdirectory like
`a1ed6c59/01-call-name/`?

**A**: That was the pre-Phase-2 layout. We flattened it in v1.0.5
because:

* the Baustein's chat notification just wants a **path** — the
  per-call subdirectory name added no information the URL/sequence
  pair did not already carry;
* the HTML / Markdown / JSON view of the same result needs to share
  the same `<NN>` so the three views can be opened together;
* the response-validator's
  `<WORK_DIR>/session/<sid>/results/` regex-filter is much simpler
  on the flat layout.

## 5. Operator notes

* The migration is idempotent. Re-running it is safe.
* The backup directory `data/sessions.legacy-<ts>/` is left in place
  after a successful migration; remove it manually after one release
  cycle once you are confident the new layout is stable.
* Pre-1.0.5 `work/` and `work.backup-*` are renamed, not deleted.
  They are safe to `rm -rf` after a release cycle:
  `rm -rf data/work.legacy-empty-* data/work.backup-*.legacy-empty-*`
* The migration is run automatically on every service start unless
  you pass `--with-migration=false`. The CLI script remains the
  operator-facing entry point for manual replay or verification.
