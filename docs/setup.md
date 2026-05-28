# Scout setup

Scout lives in two repos:

- **code repo** (this one) — the Python project. Versioned with code releases.
- **data repo** — your topics, live `scout.toml`, generated digests, and per-machine state and logs. You bootstrap this once per machine and point scout at it via `$SCOUT_DATA_DIR` (or `--data-dir`).

## First-time bootstrap

```sh
# 1. Clone the code repo and install
git clone https://github.com/<you>/scout.git ~/git/scout
cd ~/git/scout
uv sync

# 2. Create the data repo
mkdir -p ~/git/scout-data/{topics,output,state,logs}
cd ~/git/scout-data
git init -b main
cp ~/git/scout/scout.toml.example ./scout.toml
printf "state/\nlogs/\n" > .gitignore
git add .
git commit -m "scout-data: initial layout"
# create a GitHub repo and push
# git remote add origin git@github.com:<you>/scout-data.git
# git push -u origin main

# 3. Point scout at the data repo
export SCOUT_DATA_DIR=~/git/scout-data
```

Add `export SCOUT_DATA_DIR=~/git/scout-data` to your shell rc file so it's set in every interactive session.

## Running scout

Any subcommand reads `$SCOUT_DATA_DIR` (or accepts `--data-dir` to override):

```sh
scout tick                       # uses $SCOUT_DATA_DIR
scout --data-dir /tmp/scratch tick   # override for ad-hoc runs
```

If neither is set, scout exits with `scout: no data directory configured: set $SCOUT_DATA_DIR or pass --data-dir`.

### Output directory

By default digests are written under `<data-dir>/output/`. To write them
elsewhere, set `$SCOUT_OUTPUT_DIR` or pass `--output-dir`; the flag wins over the
env var, and the path may live outside the data repo:

```sh
scout --output-dir ~/scout-digests tick      # custom output location
SCOUT_OUTPUT_DIR=~/scout-digests scout tick   # same, via env
```

`topics/`, `state/`, `logs/`, and `scout.toml` always stay under the data
directory. The output directory is created on demand if it does not exist.

## Cron

```
*/15 * * * * SCOUT_DATA_DIR=/home/you/git/scout-data cd /home/you/git/scout && uv run scout tick
```

`cd` to the code repo so `uv run` finds the project; the data repo path is supplied via env.

## Editing topics

Topic YAMLs live in `$SCOUT_DATA_DIR/topics/`. Edit, commit, and push them from the data repo as you would any other file. Scout only writes the digests it generates under `$SCOUT_DATA_DIR/output/`; commit and push those yourself along with your topic changes.
