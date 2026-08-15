<!--
Keep this short. The diff shows what changed — this should say what a reviewer
can't get from reading it.
-->

## What and why

<!-- A sentence or two: what this does, and what problem it solves. -->

## Notes for the reviewer

<!--
Optional — delete if the diff speaks for itself. Worth writing when there's a
decision that isn't obvious from the code: a tradeoff you made, an approach you
rejected, a constraint that forced an odd-looking shape, or something you're
unsure about and want a second opinion on.
-->

## Checklist

Always:

- [ ] `make lint` and `make fmt` leave no changes
- [ ] `make test` passes, including the coverage gate (see `fail_under` in `pyproject.toml`)
- [ ] `venv/bin/python -m mypy src/` is clean — CI runs it over every module
- [ ] Tests added or updated for behaviour changes

If the change touches **themes, components, or anything that renders**:

- [ ] Pixel-hash baselines regenerated and committed:
      `UPDATE_SNAPSHOTS=1 pytest tests/test_theme_pixel_snapshots.py`
      (a new theme fails the coverage guard without a baseline; regenerate under the
      Pillow version in the baseline's `reference_env` so unrelated hashes don't churn)
- [ ] Preview PNGs regenerated for any theme whose appearance changed — see
      [docs/previews.md](../docs/previews.md)
- [ ] If a refactor was meant to be pixel-neutral, the unrelated theme hashes are
      confirmed **unchanged**

If the change touches **docs or user-facing behaviour**:

- [ ] `make docs-check` passes
- [ ] Canonical docs updated per the
      [Docs Update Policy](../CONTRIBUTING.md#docs-update-policy) — a new theme needs
      an inventory entry, a table row, and a `#### <name>` block with its preview in
      `docs/themes.md`, or `make docs-check` fails
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`

If the change adds a **config option**:

- [ ] Field, parser and validation wired up in `src/config.py` /
      `src/config_validation.py`
- [ ] `config/config.example.yaml` and `docs/configuration.md` updated
- [ ] `FieldSpec` added to `src/config_schema.py` if it should be web-editable
      (`secret=True` for credentials)

If the change affects **architecture or contributor workflow**:

- [ ] `CLAUDE.md` and/or `docs/architecture.md` updated

<!--
See CONTRIBUTING.md for the per-area walkthroughs (Adding a Theme / a Fetcher /
a Config Option) and docs/development.md for the registry recipes.
-->
