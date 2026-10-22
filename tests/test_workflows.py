"""The paper-trading workflows' database restore step, run against local git repos."""
import gzip
import shutil
import subprocess
from pathlib import Path

import pytest

from wxbot.config import load_config

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ["paper-trading.yml", "paper-trading-100.yml", "paper-trading-v3.yml"]
pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")


def step_script(name: str, step: str) -> str:
    """The `run: |` block of the step whose name starts with `step`."""
    lines = (ROOT / ".github/workflows" / name).read_text().splitlines()
    i = next(k for k, line in enumerate(lines) if line.strip().startswith(f"- name: {step}"))
    assert lines[i + 1].strip() == "run: |"
    body = []
    for line in lines[i + 2:]:
        if line and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body).strip() + "\n"


def job_env(name: str) -> dict[str, str]:
    """The job's `env:` block: {name: value}, quotes and comments removed."""
    lines = (ROOT / ".github/workflows" / name).read_text().splitlines()
    env = {}
    for line in lines[lines.index("    env:") + 1:]:
        if not line.startswith(" " * 6):
            break
        key, _, value = line.strip().partition(": ")
        value = value.split("  #")[0].strip()
        env[key] = value[1:-1] if len(value) > 1 and value[0] == value[-1] == '"' else value
    return env


def bot_config(name: str):
    """config.toml with the workflow's WXBOT_ overrides (not its database path, which only CI can expand)."""
    env = job_env(name)
    return load_config(env={k: v for k, v in env.items() if k.startswith("WXBOT_") and k != "WXBOT_APP__DATABASE_URL"})


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def origin_with(tmp_path: Path, files: dict[str, bytes] | None) -> str:
    """A bare repo with a `state` branch holding `files` (no branch when None); -> its file:// URL."""
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    if files is not None:
        src = tmp_path / "src"
        src.mkdir()
        git(src, "init", "-q", "-b", "state")
        for name, data in files.items():
            (src / name).write_bytes(data)
        git(src, "add", "-A")
        git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "state")
        git(src, "push", "-q", str(bare), "state")
    return bare.as_uri()


def run_restore(tmp_path: Path, name: str, url: str) -> tuple[subprocess.CompletedProcess, Path]:
    work, state = tmp_path / "work", tmp_path / "state"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "remote", "add", "origin", url)
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path), "STATE_BRANCH": "state",
           "STATE_DIR": str(state)}
    proc = subprocess.run(["bash", "-eo", "pipefail", "-c", step_script(name, "Restore database")], cwd=work, env=env,
                          capture_output=True, text=True)
    return proc, state


@pytest.mark.parametrize("name", WORKFLOWS)
def test_a_missing_state_branch_starts_a_fresh_experiment(tmp_path, name):
    proc, state = run_restore(tmp_path, name, origin_with(tmp_path, None))
    assert proc.returncode == 0 and "starting a fresh experiment" in proc.stdout
    assert list(state.iterdir()) == []


@pytest.mark.parametrize("name", WORKFLOWS)
def test_the_saved_database_is_restored(tmp_path, name):
    db = b"SQLite format 3\x00" + bytes(range(256)) * 50
    proc, state = run_restore(tmp_path, name, origin_with(tmp_path, {"wxbot.sqlite3.gz": gzip.compress(db),
                                                                     "REPORT.md": b"# r\n"}))
    assert proc.returncode == 0, proc.stderr
    assert (state / "wxbot.sqlite3").read_bytes() == db and not (state / "wxbot.sqlite3.gz").exists()


@pytest.mark.parametrize("name", ["paper-trading-100.yml", "paper-trading-v3.yml"])
def test_a_database_saved_in_parts_is_joined(tmp_path, name):
    db = bytes(range(256)) * 400
    gz = gzip.compress(db, compresslevel=0)
    parts = {f"wxbot.sqlite3.gz.part-{i:02d}": gz[i * 40000:(i + 1) * 40000] for i in range(3)}
    assert sum(len(p) for p in parts.values()) == len(gz)
    proc, state = run_restore(tmp_path, name, origin_with(tmp_path, parts))
    assert proc.returncode == 0, proc.stderr
    assert (state / "wxbot.sqlite3").read_bytes() == db and not list(state.glob("*.part-*"))


@pytest.mark.parametrize("name", WORKFLOWS)
def test_an_unreachable_state_branch_stops_the_run_instead_of_starting_over(tmp_path, name):
    proc, state = run_restore(tmp_path, name, (tmp_path / "nowhere.git").as_uri())
    assert proc.returncode != 0 and "refusing to start over" in proc.stdout
    assert not (state / "wxbot.sqlite3").exists()


@pytest.mark.parametrize("name", WORKFLOWS)
def test_a_state_branch_without_a_database_stops_the_run(tmp_path, name):
    proc, _ = run_restore(tmp_path, name, origin_with(tmp_path, {"REPORT.md": b"# r\n"}))
    assert proc.returncode != 0 and "holds no database" in proc.stdout


def test_experiment_3_refuses_code_without_the_v2_model(tmp_path):
    wf = (ROOT / ".github/workflows/paper-trading-v3.yml").read_text()
    assert wf.index("uses: actions/checkout@v4") < wf.index("- name: Check the code has the v2 model") \
        < wf.index("- name: Restore database")
    guard = step_script("paper-trading-v3.yml", "Check the code has the v2 model")
    old = subprocess.run(["bash", "-eo", "pipefail", "-c", guard], cwd=tmp_path, capture_output=True, text=True)
    assert old.returncode != 0 and "predates the v2 model" in old.stdout
    assert subprocess.run(["bash", "-eo", "pipefail", "-c", guard], cwd=ROOT).returncode == 0


def test_experiment_3_bets_on_the_model_without_the_market_check():
    cfg = bot_config("paper-trading-v3.yml")
    assert cfg.app.mode == "paper" and cfg.bankroll.initial == 100.0 and cfg.experiment.name == "exp3-v3-100usd"
    assert cfg.market_anchor.enabled is False
    assert cfg.strategy.min_model_prob < 1                 # it can bet
    # experiment 2 stays stopped: no probability reaches its threshold
    assert bot_config("paper-trading-100.yml").strategy.min_model_prob > 1
