# pipeline

Data-refresh pipeline code. The data repository is `rust-game-icons`; this
directory is self-contained and can be moved into a separate private repository
without touching the code: every path is resolved from the root.

The runbook — what to set up on Kaggle, which secrets and variables GitHub
needs, how the Steam login works — is `SETUP.md` at the repository root.

## Layout

```
<root>/
  .github/workflows/     # GitHub Actions; GitHub only reads this exact path
    validate.yml         # PR check, no secrets, ~2 min
    pipeline.yml         # gate -> fetch -> parse -> Kaggle -> validate -> PR
  .pipeline/
    paths.py             # shared path resolution
    extract_*.py         # game bundle readers
    sync_*.py            # icon and translation sync
    find_untranslated.py # missing-translation report
    kernel/              # Kaggle kernel: delta upscaling
    scripts/             # CI steps: gate, delta, kernel, dispatch, merge, PR
    tools/               # filelist generator, Steam fetch, bundle inspector
    schemas/             # JSON Schema for items.json and items.compact.json
    models/              # upscale weights, filled by hand (never committed)
```

`build/` and `out/` are created at runtime and stay out of git.

## Automation

`pipeline.yml` is one job on `ubuntu-latest`, scheduled for 19:10 UTC on days
1–7 of the month. `scripts/is_patch_day.py` narrows that to the first Tuesday,
which is when Rust force-updates. Game files are ~4.7 GiB — too large for a
500 MB artifact — so everything stays in one job rather than passing them
between jobs.

## Secrets

Nothing here reads a credential that is not passed through the environment.
A Steam maFile is held in memory only, a maFile path inside the repository is
refused, the Steam password is passed on stdin rather than argv, and
`tools/steam_fetch.py` refuses to authenticate in a pull-request context where
the code may come from a fork. See `SETUP.md` for the full threat model.

## Game paths

Not a single hardcoded path. Set via environment variables or flags:

| Variable | Meaning |
|---|---|
| `RUST_GAME_DIR` | Rust install root |
| `RUST_ITEMS_BUNDLE` | path to `items.preload.bundle` |
| `RUST_CONTENT_BUNDLE` | path to `content.bundle` |
| `RUST_ITEMS_DIR` | `Bundles/items` folder |
| `RUST_UPSCALE_BACKEND` | `upscayl` (default), `torch` or `none` |
| `RUST_UPSCALER_MODEL_PATH` | path to a `.pth` for the torch backend |
| `STEAM_USERNAME` / `STEAM_PASSWORD` | Steam login, read by `tools/steam_fetch.py` only |
| `STEAM_MAFILE_B64` / `STEAM_MAFILE` | Steam Guard, base64 or path |
| `DEPOTDOWNLOADER` | path to the `DepotDownloader` binary |

## Fetching the game

```bash
python .pipeline/tools/steam_fetch.py --anonymous --app 258550 --dest game-assets/server
```

The dedicated server needs no login. The client depot does; see `SETUP.md` for
the maFile procedure and the account rules before you create one.

## Running the parser locally

```bash
python -m pip install -r .pipeline/requirements-actions.txt
set RUST_GAME_DIR=E:\SteamLibrary\steamapps\common\Rust
python .pipeline/sync_all.py --only localization,craft,recycle,translations
```

## Local check without CI

```bash
python .pipeline/scripts/validate_outputs.py --repo-dir .
```

Needs no secrets, no game files and no network. Fails on key mismatches,
missing icons, broken schemas and translation regressions.

## Source of the files

Depot 252494 "Rust Client - Common", via `DepotDownloader -filelist` —
4.67 GiB instead of 30 GiB. Generate the list with:

```bash
python .pipeline/tools/make_filelist.py wanted --out wanted.txt
```

The download is done manually and locally on purpose: the Steam refresh token
never reaches CI.