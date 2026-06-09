# Project Assessment & Improvement Plan

*Assessed 2026-06-09 against `main` (post-#186, moonphase_photo theme).*

## Current state

The project is in very good health. Findings from a full local audit:

| Check | Result |
|---|---|
| Test suite | 2,786 passed, 0 failed (42 s) |
| Coverage | 95.7 % (gate: 90 %) |
| `ruff check` / `ruff format --check` | Clean (229 files) |
| `mypy src/` | Clean (132 files) — but see P1-1 |
| `make docs-check` | OK |
| Smoke render (`--dry-run --dummy`) | OK |
| TODO / FIXME / HACK markers | None |
| Open GitHub issues / PRs | None |

CI is unusually thorough for a hobby project: a 3-version test matrix,
a bare-`pip install .` core-dependency guard, a Pillow-pinned pixel-snapshot
job, mypy, and a dummy-render smoke job. The v5 registry architecture
(fetchers / themes / components) is consistently applied, state writes are
atomic, and datetime discipline is enforced by a custom AST guard.

The improvement plan below is therefore mostly *forward-compatibility and
identity debt*, not bug fixing. Items are ordered by priority; each is
sized small (S, < 1 h), medium (M, an afternoon), or large (L, multi-day).

---

## P0 — Forward-compatibility and identity debt

### P0-1. Cut the v5.0 release identity (S)

The codebase *is* v5 (CLAUDE.md says "Dashboard v5"; CHANGELOG has a
`[5.0.0] — Pluggable & Polished` section) but the package identity still
says v4:

- `src/_version.py` → `__version__ = "4.6"` (`--version` prints "main.py 4.6")
- `pyproject.toml` → `name = "dashboard-v4"`, `version = "4.6"`
- `CHANGELOG.md` → `[5.0.0]` has no release date, and the `[Unreleased]`
  section has accumulated six shipped themes (postcard, naturalist,
  light_cycle, almanac, weatherglass, moonphase_photo, …)

**Plan:** rename the package (e.g. `home-dashboard`), set version `5.1.0`,
date the 5.0.0 entry, roll the Unreleased block into a dated 5.1.0 entry,
and tag the release. Also fix the stray `## [4.2] - Unreleased` heading in
the changelog history.

### P0-2. Remove deprecated Pillow `getdata()` (M)

`Image.getdata()` is deprecated and **will be removed in Pillow 14
(2027-10-15)**. Running the suite with `-W error::DeprecationWarning`
fails 97 tests. Production call sites:

- `src/render/quantize.py:135` — Floyd–Steinberg fallback path
- `src/render/quantize.py:243,354` — palette mapping (the comment at
  line 242 even says "Avoid deprecated getdata()" but still calls it)
- `src/render/themes/photo.py:89` — dither verification

Plus ~10 test files (`test_quantize.py` alone has 33 uses).

**Plan:** numpy is already a core dependency — replace the production
`list(image.getdata())` calls with `numpy.asarray(image)` (faster too),
and give tests a tiny shared `pixel_values(img)` helper in `tests/`
conftest. Then add `filterwarnings = ["error::DeprecationWarning"]` to
`[tool.pytest.ini_options]` so the next upstream deprecation fails CI
immediately instead of accumulating 100+ silent warnings.

### P0-3. Retire the Python 3.9 floor (S–M)

Python 3.9 reached end-of-life in October 2025. Today:

- `mypy` warns `python_version: Python 3.9 is not supported` and silently
  type-checks under a different version than the declared floor — the
  declared floor is effectively unverified by the type checker.
- The ruff config carries `ignore = ["UP007"]` and the codebase carries
  `from __future__ import annotations` workarounds purely for 3.9.
- Pi OS Bookworm (current) ships Python 3.11; Bullseye (3.9) is EOL.

**Plan:** bump `requires-python = ">=3.10"` (or 3.11 to match the Pi),
set `[tool.ruff] target-version` and `[tool.mypy] python_version`
accordingly, drop the `UP007` ignore and let ruff modernise annotations,
and replace 3.9 with 3.13 in the CI test matrix.

---

## P1 — Strengthen the quality gates

### P1-1. Burn down the mypy `ignore_errors` blanket (L, incremental)

29 of the 30 render-component modules — the majority of the codebase by
line count — are excluded from type checking via `ignore_errors = true`
in `pyproject.toml`. The stated root cause is `Optional[FontCallable]`
fields on `ThemeStyle` that `__post_init__` guarantees non-None but mypy
can't prove. "mypy: clean" currently means *clean except the render layer*.

**Plan:** fix the root cause once — give `ThemeStyle` non-Optional typed
accessors (e.g. `def title_font(self, size: int) -> FreeTypeFont`,
mirroring the existing `primary_accent_fill()` pattern), or resolve the
fallbacks in `__post_init__` into non-Optional fields. Then remove
modules from the override list a few per PR until the list is empty.
This also de-risks every future theme PR, which is where most churn happens.

### P1-2. True up the coverage story (S)

Actual coverage is **95.7 %**; CLAUDE.md claims "currently ~99 %" and the
gate is 90 %. The biggest gaps are the newest art panels
(`weatherglass_panel`, `postcard_panel`, `naturalist_panel`).

**Plan:** raise `fail_under` from 90 to 94 so the ratchet reflects
reality and new code can't regress below it, and correct the CLAUDE.md
claim. Optionally add targeted tests for the untested branches in the
art panels (mostly weather-variant scene paths).

---

## P2 — Render-layer maintainability

### P2-1. Extract shared drawing/data helpers (M)

The procedural art panels have grown organically and now duplicate
concepts:

- `_season(today)` is defined identically in `almanac_panel.py:151` and
  `naturalist_panel.py:146`, with a third season implementation in
  `services/theme_rules.py`.
- Mode-aware colour helpers (`_grey(v, mode)`, `_ink(mode)`, brass/
  mercury variants) and the supersample-then-quantize scaffolding repeat
  across `weatherglass_panel`, `postcard_panel`, `naturalist_panel`,
  `halftone_panel`, and `sunrise_panel`.

**Plan:** add `src/render/artkit.py` (or extend `primitives.py`) with the
shared season helper, mode-aware colour resolution, and the dither/
supersample scaffolding. Pixel-snapshot tests make this refactor safe —
any behavioural drift shows up as a hash change.

### P2-2. Split the two oversized modules (M, optional)

- `weatherglass_panel.py` is 1,977 lines with 41 private helpers; the
  generic instrument primitives (`_draw_dial_rim`, `_draw_needle`,
  `_rotate_text_paste`, `_fill_zone`) are reusable and would seed the
  artkit module above.
- `config.py` is 1,006 lines mixing dataclass definitions, YAML parsing,
  and `validate_config()`. Splitting validation into its own module
  would shrink the file and remove the lazy-PIL-import wart that web
  tests currently have to patch around.

Both are well-tested, so this is purely about keeping future edits cheap.

---

## P3 — Roadmap features (v5.1+)

In priority order, all grounded in existing deferrals or natural
extensions:

1. **Web UI patch-preview** — explicitly deferred from v5: render a theme
   preview against a *candidate* config diff before saving, so config
   edits can be verified visually. The plumbing
   (`POST /api/preview`, `apply_patch()` temp-file validation) already
   exists; this composes them.
2. **Theme-rules editor in the web UI** — `theme_rules` is the most
   powerful config feature and the only major one not editable from the
   schema-driven web form (it's a nested list, which `FieldSpec` doesn't
   model). Even a validated raw-YAML textarea with preview would help.
3. **requirements.txt drift guard** — `requirements.txt` hand-mirrors
   `[project].dependencies` for Pi deployment. Add a trivial CI step that
   parses both and fails on divergence.
4. **Pi-side health surfacing** — the web UI already reads
   `last_success.txt` / `last_error.txt`; consider a small
   `GET /api/health` returning 200/503 for use with uptime monitors
   (Uptime Kuma, healthchecks.io).

---

## Suggested sequencing

| Phase | Items | Outcome |
|---|---|---|
| 1 (one sitting) | P0-1, P0-3, P1-2 | Honest version, supported toolchain, honest gates |
| 2 (one PR) | P0-2 + deprecation-as-error | Pillow-14-proof, future deprecations fail fast |
| 3 (incremental PRs) | P1-1, P2-1 | Full type coverage; shared art toolkit |
| 4 (as desired) | P2-2, P3 items | Cheaper future themes; v5.1 feature set |
