# CI and environments

Spec section 21 asks for automated tests, linting, type checking, build and
Docker checks, and separate development, testing, staging and production
stages, so that a commit never deploys an untested model.

## The checks

`.github/workflows/tests.yml` runs on every pull request and every push to
`main`:

| Job | What it checks |
|---|---|
| `lint` | `ruff check .` with the rules in `pyproject.toml` (pycodestyle, pyflakes, bugbear, pyupgrade) and `shellcheck` on the deploy scripts; also fails if `uv.lock` no longer matches `pyproject.toml` |
| `types` | `mypy` on `wxbot/` and `main.py` |
| `pytest` | the offline test suite with coverage; fails below the floor in `pyproject.toml` (90%) and writes the coverage table to the run's summary page |
| `build` | a plain `pip install -r requirements.txt` (what the Docker image and the Actions experiments install), every module compiles and imports, and the app starts on a fresh database in paper mode |

`.github/workflows/docker.yml` builds and starts the image whenever the
Dockerfile, compose file, `deploy/` or the requirements change (README,
"Running on a server").

Run the same checks locally with `uv sync && uv run ruff check . && uv run mypy
&& uv run pytest --cov`, or with pip: `pip install -r requirements-dev.txt`.

## The stages

| Stage | Where | What runs there |
|---|---|---|
| Development | a branch and its pull request | the checks above on every push |
| Testing | `tests.yml` and `docker.yml` | lint, types, tests, build, image |
| Staging | `main` | a merged commit waits here until its CI passes. Before merging a model change, `backtest-markets` can replay past markets with it on its own research database |
| Production | the experiments and a server | experiment 2 and `deploy/update.sh` run only the newest commit of `main` that passed CI ([deploy.md](deploy.md)); experiment 1 runs its frozen branch |

**Code.** `paper-trading-100.yml` asks GitHub for the newest push to `main`
on which the whole `tests` workflow passed and checks out that commit. While a
new commit's CI is still running, or if it fails, runs keep using the last
green commit; if none has ever passed, the run refuses to start. The commit
that ran is recorded as `WXBOT_GIT_REF`, so every result can be traced to code
that passed CI.

**Models.** Code passing CI does not change the model by itself: the station
bias/spread sets and the probability calibrators are only replaced inside a
running experiment, and only when they beat the ones in use on data they were
not fitted on (README, "How the learning system works"), with a rollback when
a new set then does worse.
