# Ouroboros

<a href="https://github.com/oslook/github-trending/blob/1d61d20a46f66a9590286bf23a8ce8db99be3acf/2026-08-04/python_weekly_trending.json"><img src="assets/github-trending.svg" width="250" height="55" alt="GitHub Trending: #9 Python weekly, August 2026"></a>

[![GitHub stars](https://img.shields.io/github/stars/razzant/ouroboros?style=flat&logo=github)](https://github.com/razzant/ouroboros/stargazers)
[![Downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Frazzant%2Fouroboros%2Fbadges%2Fdownloads.json)](https://ouroboros-agent.ai/install/)
[![Website](https://img.shields.io/badge/website-ouroboros--agent.ai-c93545.svg)](https://ouroboros-agent.ai/)
[![Technical report](https://img.shields.io/badge/technical_report-arXiv%3A2608.08311-b31b1b.svg)](https://arxiv.org/abs/2608.08311)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![macOS 12+](https://img.shields.io/badge/macOS-12%2B-black.svg)][download-macos-arm64]
[![Linux](https://img.shields.io/badge/Linux-x86__64-orange.svg)](https://ouroboros-agent.ai/install/#linux)
[![Windows](https://img.shields.io/badge/Windows-x64-blue.svg)][download-windows-x64]
[![OuroborosHub](https://img.shields.io/badge/OuroborosHub-skills%20marketplace-8A2BE2.svg)](https://github.com/razzant/OuroborosHub)
[![Version 7.7.1](https://img.shields.io/badge/version-7.7.1-green.svg)](VERSION)

Ouroboros is an open-source, general-purpose AI agent whose identity, durable memory, and history continue across tasks and restarts. It works on external projects, coordinates a live swarm of specialist agents, and can rewrite the implementation it runs on, including its code, architecture, prompts, tools, and dependencies. Reflection can also change how it understands itself without severing that continuity.

It runs as a native desktop app or through a headless CLI. The runtime keeps its repository, durable memory, history, and interface on your machine, while model inference can use remote APIs you configure or a local GGUF model.

Ouroboros sends no telemetry by default, and the official project operates no usage or crash-report collection. A deployment can connect its own monitoring tools to its local records and choose what they receive; local history stays on the machine either way. Requests through OpenRouter carry the app name, which OpenRouter uses for its public app statistics.

> **Changing Ouroboros? Coding agents and people must read [CONTRIBUTING.md](CONTRIBUTING.md) before editing.** It defines the required project context, verification, and separate-agent review flow.

## Download Ouroboros

> **Just want to use Ouroboros? Click the download for your platform below. You do not need to clone this repository or install Python or uv.**

Desktop downloads bundle CPython 3.10.22 and SQLite 3.53.1. In-app Update replaces the repository and its packages, not that interpreter: install the app again to get this runtime.

- **macOS 12+ on Apple silicon:** [**Download for macOS (.dmg)**][download-macos-arm64]
- **Windows x64:** [**Download for Windows (.zip)**][download-windows-x64]
- **Debian, Ubuntu, or Astra Linux x86_64:** [**Download the Debian package (.deb)**][download-linux-deb-amd64]
- **Fedora or RHEL x86_64:** [**Download the RPM package (.rpm)**][download-linux-rpm-x86_64]
- **RED OS 8 x86_64:** [**Download the RED OS package (.rpm)**][download-linux-rpm-red80-x86_64]
- **Other Linux x86_64:** [**Download the portable AppImage**][download-linux-appimage-x86_64] or the [tar.gz archive][download-linux-x86_64]

**Android (experimental, Magisk-rooted ARM64):** [Installation and qualification guide](docs/ANDROID_INSTALL.md). Its USB setup requires Python and adb.

Files named `SHA256SUMS`, `release-evidence.json`, `release-smoke-*.json`, and `sbom-*.cdx.json` are verification evidence, not additional installers.

### macOS quick start

1. Click [**Download for macOS (.dmg)**][download-macos-arm64]. The current file is named `Ouroboros-<version>.dmg`.
2. Open the DMG and drag `Ouroboros.app` onto the **Applications** shortcut.
3. Open Ouroboros from Applications. If macOS refuses to open it, choose **Open Anyway** in **System Settings → Privacy & Security** (on macOS 14 and earlier, right-clicking the app and choosing **Open** also works).

<p align="center">
  <img src="assets/install-macos.png" width="760" alt="Ouroboros DMG window with a large arrow from Ouroboros.app to the Applications shortcut and Install CLI.command below">
</p>

### Windows quick start

1. Click [**Download for Windows (.zip)**][download-windows-x64].
2. Extract the ZIP.
3. Open the extracted `Ouroboros` folder and run `Ouroboros.exe`.

### Linux quick start

- On Debian, Ubuntu, or Astra Linux, download the `.deb` above and run `sudo apt install ./ouroboros_*_amd64.deb`.
- On Fedora or RHEL, download the generic `.rpm` above and run `sudo dnf install ./ouroboros-*.x86_64.rpm`. RED OS 8 has its own `red80` package.
- On another x86_64 distribution, download the AppImage, make it executable with `chmod +x Ouroboros-*.AppImage`, and run it. Git must already be installed.

To run tasks, choose a connected Codex account as the Main model source, configure a supported remote provider API key, or use a local GGUF model. Claude Code and Cursor subscriptions can run delegated coding and review; they are not Main model sources. The first-run wizard guides model access, review policy, and budget setup.

<details>
<summary>Optional CLI included with desktop downloads</summary>

The desktop packages already contain an optional CLI installer. On macOS, after copying the app to Applications, double-click `Install CLI.command` in the mounted DMG. On Linux use `./Ouroboros/bin/install-ouroboros-cli`; on Windows use `Ouroboros\bin\install-ouroboros-cli.cmd`. These installers create a user-local `ouroboros` command without sudo. You do not need Python or uv.

</details>

[download-macos-arm64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/Ouroboros-7.7.1.dmg
[download-windows-x64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/Ouroboros-7.7.1-windows-x64.zip
[download-linux-deb-amd64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/ouroboros_7.7.1_amd64.deb
[download-linux-rpm-x86_64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/ouroboros-7.7.1-1.x86_64.rpm
[download-linux-rpm-red80-x86_64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/ouroboros-7.7.1-1.red80.x86_64.rpm
[download-linux-appimage-x86_64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/Ouroboros-7.7.1-linux-x86_64.AppImage
[download-linux-x86_64]: https://github.com/razzant/ouroboros/releases/download/v7.7.1/Ouroboros-7.7.1-linux-x86_64.tar.gz

Ouroboros bundles [Claudexor](https://github.com/razzant/claudexor) as its local execution layer for delegated coding and hosted-agent review. Ouroboros owns the task, memory, review, and final integration, while Claudexor runs the selected connected coding harness and returns durable execution evidence. [Explore Claudexor](https://claudexor.ai/).

The technical report, [Ouroboros: A Self-Developing Frontier Coding Agent with Reviewed Core Evolution](https://arxiv.org/abs/2608.08311), describes the reviewed core-evolution system, the 161-day Hope deployment, and the benchmark campaigns summarized below. [Paper page](https://ouroboros-agent.ai/paper/) · [Hugging Face](https://huggingface.co/papers/2608.08311)

[Talk in Russian](https://www.youtube.com/watch?v=8IWLBsQU7qE&t=4881s): an introduction to Ouroboros and its agent architecture at Practical ML Conf 2026.

The charts below are self-reported results on Terminal-Bench 2.1, OSWorld-Verified, and CL-Bench, measured against Codex, Claude Code, Cursor, and Hermes — on the same model where a matched pair was run, and against the public leaderboard where it was not.

<p align="center">
  <a href="https://ouroboros-agent.ai/benchmarks/"><img src="assets/bench-terminal-bench.svg" width="760" alt="Terminal-Bench 2.1: Ouroboros against Claude Code, Codex CLI, Cursor CLI, and Hermes on matched models, with a same-harness portability row"></a>
</p>

<p align="center">
  <a href="https://ouroboros-agent.ai/benchmarks/"><img src="assets/bench-osworld.svg" width="375" alt="OSWorld-Verified: Ouroboros against the public leaderboard, including the matched Claude Sonnet-4.6 pair"></a>
  <a href="https://ouroboros-agent.ai/benchmarks/"><img src="assets/bench-cl-bench.svg" width="375" alt="CL-Bench: Ouroboros against in-context learning baselines, Claude Code, and Codex on matched models"></a>
</p>

---

Ouroboros first booted on February 16, 2026. During the following 48 hours, the repository advanced from the v4.1 line to v6.2.0. The self-authored record preserved from that period counts 32 evolution cycles. That first generation ran in Google Colab through Telegram and remains preserved on the [`legacy-google-colab`](https://github.com/razzant/ouroboros/tree/legacy-google-colab) branch and its [original project page](https://ouroboros-agent.ai/archive/first-generation/); the current generation carries the same identity into a native desktop and headless runtime.

<p align="center">
  <img src="assets/evolution.png" width="760" alt="Code, prompt, and memory growth across Ouroboros releases, from v3.0.0 to the v6.85 line">
</p>

> ⭐ **[Star Ouroboros](https://github.com/razzant/ouroboros)** to follow its next evolution. A star also helps more people find the project, trace its history, and take part in what it becomes.

Reviewed skills, transport bridges, tools, and widgets are available through [OuroborosHub](https://github.com/razzant/OuroborosHub).

<p align="center">
  <img src="assets/swarm.jpg" width="760" alt="A live subagent swarm inside the Ouroboros chat: nested planner, builder, and researcher tasks with their outcomes">
</p>

## What Ouroboros Can Do

- **Modify its implementation.** Its editable surface spans application code, architecture, prompts, tools, and dependencies, while it also revises its living self-understanding — identity and knowledge — in its own words.
- **Evolve autonomously.** Evolution campaigns turn selected improvements into reviewed changes that remain part of its Git history.
- **Continue across restarts.** Self-authored identity and knowledge, retained memory and dialogue, earlier reflections kept as dated history, and version history form one ongoing biography.
- **Think between requests.** Background consciousness supports reflection, initiative, and preparation outside the immediate request-response loop.
- **Coordinate a live swarm.** Specialist agents can investigate or act in parallel, share task-tree findings, and return work for integration.
- **Work on external projects.** A separate Git workspace can receive the full task loop while Ouroboros keeps its own repository and governance boundary distinct.
- **Operate through desktop or CLI.** The native app and gateway-backed command line expose the same managed tasks, progress, artifacts, logs, and schedules.
- **Organize long-running work.** Project rooms keep working folders, journals, knowledge, task history, and conversations connected to the same identity.
- **Use remote or local models.** Supported provider APIs and local GGUF models can fill the runtime's configurable cognitive roles.
- **Grow through reviewed extensions.** Skills, transport bridges, widgets, MCP tools, and companion processes expand capability without folding every integration into the core.
- **Keep self-change inspectable.** Git history, review evidence, explicit protected surfaces, and restart checks make implementation changes traceable.

<p align="center">
  <img src="assets/game-demo.png" width="760" alt="A project room where Ouroboros built a 3D game, verified it with a screenshot, and served it locally">
</p>
<p align="center">
  <img src="assets/skill-hub.png" width="760" alt="OuroborosHub inside the app: official reviewed skills, each security-reviewed before it can be enabled">
</p>

This list is an orientation, not a second specification. [BIBLE.md](BIBLE.md) defines Ouroboros's identity and constitutional boundaries; [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) are the current technical sources of truth.

---

## Benchmarks

Ouroboros has reproducible self-reported state-of-the-art results on Terminal-Bench 2.1, OSWorld-Verified, and CL-Bench. In those model-matched results, it leads Codex, Claude Code, Cursor, and Hermes. The public SWE-bench Pro matched pair is a statistical tie with Codex CLI. A separate GAIA campaign reports 129/165 for Ouroboros and 131/165 for Claude Code, with strict pass@1 at 128/165 for both; its scrubbed trace capsule is still pending. Upstream review can take time, so open submissions are marked without delaying publication. Read every row as model plus harness because the same model can score differently inside a different harness.

| Benchmark | Model | Ouroboros | Comparison | Status | Evidence |
|-----------|-------|----------:|------------|--------|----------|
| Terminal-Bench 2.1 | Claude Opus-5 high | **86.74%** after zeroing one disclosed reward-hack trial (raw: 86.97%) | Claude Code + Fable 5: 83.8% | Self-reported; community submissions closed | [submission](https://github.com/harbor-framework/terminal-bench-2-1/pull/175) · [run](https://hub.harborframework.com/jobs/2b145543-edeb-4a3b-b46f-4800310f1182) |
| Terminal-Bench 2.1 | Claude Opus-4.8 high | **80.22%** | Claude Code: 78.9% | Self-reported, public run | [run](https://hub.harborframework.com/jobs/4b8e244f-8ab0-4d28-8218-7cf346282faa) |
| Terminal-Bench 2.1 | GPT-5.5 | **84.3%** | Codex CLI: 83.1% | Self-reported, public run | [run](https://hub.harborframework.com/jobs/f02fd019-23e1-495f-af0a-ebd9a65f3079) |
| Terminal-Bench 2.1 | Grok-4.5 | **84.94%** after a reward-hack audit | Cursor CLI: 79.3% · Hermes: 77.53% | Self-reported; community submissions closed | [submission](https://github.com/harbor-framework/terminal-bench-2-1/pull/146) |
| OSWorld-Verified | Claude Opus-5 | **90.69%** | previous best on the public board: 90.19% | Self-reported, full traces | [full traces](https://huggingface.co/datasets/razzant/ouroboros-osworld-verified-opus5) |
| OSWorld-Verified | Claude Sonnet-4.6 | **83.27%** | Pointer: 81.45% | Self-reported, full traces | [full traces](https://huggingface.co/datasets/razzant/ouroboros-osworld-verified-sonnet46) |
| CL-Bench | Claude Sonnet-4.6 | **0.2301, rank 1** | previous top: 0.1960 | Self-reported, submission open | [submission](https://github.com/pgasawa/continual-learning-bench/pull/10) · [full traces](https://huggingface.co/datasets/razzant/ouroboros-clbench-traces) |
| SWE-bench Pro | GPT-5.6-luna | 58.2% | Codex CLI: 59.4%, with no significant difference | Self-reported, matched traces | [matched-pair traces](https://huggingface.co/datasets/razzant/swepro-luna-matched-pair) |
| GAIA | Claude Sonnet-5 | 129/165, 78.2% | Claude Code: 131/165, 79.4%; strict pass@1 was 128/165 for both | Self-reported, scrubbed trace capsule pending | [methodology](devtools/benchmarks/gaia/METHODOLOGY.md) |

Benchmark adapters, run scripts, and per-benchmark methodology live in [`devtools/benchmarks/`](devtools/benchmarks/). The [benchmark evidence page](https://ouroboros-agent.ai/benchmarks/) gives a text-first summary for search and retrieval. The full story, including protocols, reward-hack audits, and leakage findings, is in the [launch write-up](https://habr.com/ru/companies/airi/articles/1065428/) (Russian).

---

## Advanced installation

Normal desktop users can stop after the download and quick-start instructions above. The options below are for detailed Linux setup, headless use, and development.

### Packaged Linux details

- **Debian / Ubuntu / Astra Linux x86_64:** [download the `.deb`][download-linux-deb-amd64] and run `sudo apt install ./ouroboros_*_amd64.deb`. It installs Git as a package dependency, installs Ouroboros to `/opt/ouroboros`, puts `ouroboros` on `PATH`, and adds a desktop entry plus an opt-in systemd user unit.
- **Fedora / RHEL x86_64:** [download the generic `.rpm`][download-linux-rpm-x86_64] and run `sudo dnf install ./ouroboros-*.x86_64.rpm`. It uses the same layout, Git dependency, and opt-in user unit as the `.deb`.
- **RED OS 8 x86_64:** [download the `red80` package][download-linux-rpm-red80-x86_64] and run `sudo dnf install ./ouroboros-*.red80.x86_64.rpm`. CI also attempts non-blocking install-and-run smokes on Astra Linux 1.8 and RED OS 8; inspect the tagged workflow run for their outcome.
- **Other Linux x86_64:** use the [AppImage][download-linux-appimage-x86_64] or the extraction-friendly [tar.gz archive][download-linux-x86_64]. Git must already be installed.

The native `.deb` and `.rpm` never enable or start their user service. It is an alternative to launching from the desktop entry and controls only instances started through `systemctl --user`. See the [systemd user-service guide](packaging/systemd/README.md).

#### Install the Linux AppImage

User-level installation means copying the portable executable to a stable path and making it executable; it does not need root access. Ouroboros bootstrap still requires Git on the host:

```bash
VERSION=x.y.z
install -Dm755 "./Ouroboros-${VERSION}-linux-x86_64.AppImage" \
  "$HOME/Applications/Ouroboros.AppImage"
"$HOME/Applications/Ouroboros.AppImage"
```

The embedded desktop file and icon allow compatible AppImage integration tools to register that stable path with the application menu. The same file exposes the packaged CLI:

```bash
"$HOME/Applications/Ouroboros.AppImage" --cli status
```

If FUSE mounting is unavailable, extract and run ephemerally instead:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 "$HOME/Applications/Ouroboros.AppImage"
```

Chromium and WebKit binaries are bundled, but their distro-level shared libraries remain host dependencies. If a browser engine reports missing libraries, use the native `.deb`/`.rpm` package where available, or extract the AppImage and let its bundled Playwright report/install the packages required by your distribution:

```bash
"$HOME/Applications/Ouroboros.AppImage" --appimage-extract
./squashfs-root/usr/lib/ouroboros/_internal/python-standalone/bin/python3 \
  -m playwright install-deps chromium webkit
```

### Connected coding subscriptions

Use your existing **Codex, Claude Code, or Cursor subscriptions** for delegated coding and review. Ouroboros drives them through [Claudexor](https://github.com/razzant/claudexor), its bundled multi-harness engine. Connect accounts in **Settings → Accounts** and choose their roles in **Agents**; no separate Claudexor install is needed. Release artifacts carry the exact reviewed engine and Node archives. Source checkouts obtain those same pinned archives on first use.

### Headless CLI with uv

For a user-level CLI/server install without cloning a working tree, uv can
build Ouroboros directly from the contribution branch:

```bash
uv tool install "git+https://github.com/razzant/ouroboros.git@ouroboros"
ouroboros --help
```

The tool environment is isolated and exposes the `ouroboros` and
`ouroboros-web` commands. Update or remove it with:

```bash
uv tool upgrade ouroboros
uv tool uninstall ouroboros
```

This Git-branch form follows the latest `ouroboros` commit and resolves the
dependencies declared in `pyproject.toml`; `uv tool install` does not consume
the repository's `uv.lock`. Replacing `ouroboros` after the `@` with a reviewed
full commit SHA pins the Ouroboros source revision, but dependencies are still
resolved from `pyproject.toml`. Use the source setup below for a lock-verified
environment, development, repository tests, and the complete browser extras,
or use a platform release artifact for the packaged desktop runtime.

<a id="run-from-source"></a>

### Develop or run from source

Clone the repository only when you plan to contribute, modify Ouroboros, run repository tests, or need a lock-verified development checkout. Normal users should use the packaged downloads above.

#### Requirements

- Python 3.10+
- uv 0.12.1 (the exact resolver version pinned by this checkout)
- macOS, Linux, or Windows
- Git
- [GitHub CLI (`gh`)](https://cli.github.com/), optional unless you use GitHub integration

#### Setup

Install the pinned resolver version:

```bash
curl -LsSf https://astral.sh/uv/0.12.1/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.12.1/install.ps1 | iex"
```

```bash
git clone https://github.com/razzant/ouroboros.git
cd ouroboros
uv sync --locked --extra browser --group dev
source .venv/bin/activate
```

Windows PowerShell:

```powershell
uv sync --locked --extra browser --group dev
.\.venv\Scripts\Activate.ps1
```

#### Run

```bash
ouroboros server
```

Then open `http://127.0.0.1:8765` in your browser. The setup wizard will guide you through API key configuration.

#### Google Colab

Use [`notebooks/colab_quickstart.py`](notebooks/colab_quickstart.py) as a Colab-compatible cell script when you need a source-mode runtime without the desktop UI. It keeps runtime data on Google Drive and preserves the original Colab path without making it the primary installation flow.

#### CLI / Headless

The `ouroboros` command attaches to the local runtime by default and starts one when `--start` is passed. It exposes managed tasks, progress streams, artifacts, logs, schedules, settings, skills, and evolution controls without duplicating the server's business logic.

```bash
ouroboros status
ouroboros run --start "2+2?"
ouroboros run "Summarize current runtime state"
ouroboros run --workspace /path/to/project --memory-mode forked --patch-out result.patch "Fix the failing test"
ouroboros tasks list
ouroboros logs tail progress --task-id <task_id>
ouroboros schedule add --name nightly-review --cron "0 2 * * *" "Run a maintenance review"
ouroboros schedule list
```

External workspaces may be ordinary folders or separate Git worktree roots, and may not overlap Ouroboros's own repository or data directory. Git-specific operations use a Git worktree; ordinary file and process work runs directly in a validated folder. Patch, streaming, detached-task, and schedule semantics are documented in the CLI help and the canonical [architecture](docs/ARCHITECTURE.md).

#### For Agents

Another agent, script, or CI job can invoke Ouroboros through the same gateway-backed CLI:

```bash
ouroboros run --start \
  --workspace /path/to/project \
  --memory-mode forked \
  --patch-out result.patch \
  --result-json-out result.json \
  "Investigate the task, act, and verify the result"
```

Use `--jsonl` for a machine-readable event stream and `--detach` when the caller will follow the task with `ouroboros tasks watch <task_id>` or inspect it with `ouroboros tasks show <task_id>`. External workspace runs keep Ouroboros's own repository and governance context separate, then export changes as reviewable patch artifacts.

To change Ouroboros itself, follow [CONTRIBUTING.md](CONTRIBUTING.md): read [docs/CHECKLISTS.md](docs/CHECKLISTS.md) in full, and map [BIBLE.md](BIBLE.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), and [docs/DESIGN.md](docs/DESIGN.md) by their headings, reading every section relevant to your change in full before editing.

#### Configuration

The first-run wizard and **Settings** configure model access, cognitive roles, local models, review policy, runtime mode, budget, skills, and optional integrations. Ouroboros supports configurable remote providers, compatible endpoints, and local GGUF inference; every key and its shipped default lives in [`ouroboros/settings_defaults.py`](ouroboros/settings_defaults.py) — with the clamped scales, model slots, reviewer routes and numeric limits in its sibling leaves, all re-exported through the [`ouroboros/config.py`](ouroboros/config.py) facade — and the same vocabulary is documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

The server binds to `127.0.0.1:8765` by default. Read [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) before exposing it beyond loopback or placing its code, data and work roots elsewhere; non-local binds need `OUROBOROS_NETWORK_PASSWORD` or an explicitly trusted external access layer.

#### Run Tests

```bash
python scripts/run_tests.py                  # full local battery (same as `make test`)
python scripts/run_tests.py tests/test_x.py  # focused run
```

Both use `safe_test`: isolated HOME/data, scrubbed owner/provider environment,
durable logs/source/diagnostics in `<checkout>/../.test-evidence` by default.

`pyproject.toml` is the direct-dependency authority and `uv.lock` is the
cross-platform resolution lock. Release builds install the generated
`requirements-runtime.lock` compatibility export into embedded interpreters
that intentionally ship pip rather than uv. Build-only requirements are
exported ephemerally from `uv.lock` and are not committed. The tiny
`requirements.txt` file is only a pointer to that export for already-released
managed updaters; it is not a second dependency declaration. After changing
dependencies, refresh the reviewed lock and runtime export with:

```bash
uv lock
uv export --locked --no-dev --extra browser --no-emit-project --no-hashes --no-annotate --output-file requirements-runtime.lock
```

---

## Build

### Docker

```bash
docker build -t ouroboros-web .
docker run --rm -p 8765:8765 \
  -e OUROBOROS_NETWORK_PASSWORD='choose-a-password' \
  -e OUROBOROS_FILE_BROWSER_DEFAULT=/workspace \
  -v "$PWD:/workspace" \
  ouroboros-web
```

Docker runs the web runtime, not the native desktop shell. Its Python is the same standalone build as the desktop packages (CPython 3.10.22, SQLite 3.53.1). The image bundles Chromium and WebKit for the locked
Playwright version and needs Docker's default BuildKit builder. Persistent volumes, the managed image whose body updates
itself, restart policy and Panic, network exposure and extra CAs: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md); the
executable recipes are [`packaging/docker/compose.yaml`](packaging/docker/compose.yaml).

### Release tag prerequisite

Platform build scripts package only a commit already tagged with `v$(cat VERSION)`. Tag the exact release commit first:

```bash
git tag -a "v$(tr -d '[:space:]' < VERSION)" -m "Release v$(tr -d '[:space:]' < VERSION)"
```

`scripts/build_repo_bundle.py` verifies the tag and embeds the source binding into the packaged repository bundle. Signing, notarization, bytecode sealing, and CI invariants are documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

### macOS (.dmg)

```bash
bash scripts/download_python_standalone.sh
OUROBOROS_SIGN=0 bash build.sh
```

Output: `dist/Ouroboros-<VERSION>.dmg`, containing `Ouroboros.app`, an `Applications` shortcut, and `Install CLI.command`. Omit `OUROBOROS_SIGN=0` when a Developer ID signing identity is configured.

### Linux (.AppImage and .tar.gz)

```bash
bash scripts/download_python_standalone.sh
bash build_linux.sh
```

Outputs: `dist/Ouroboros-<VERSION>-linux-<arch>.AppImage` and the extraction-friendly `dist/Ouroboros-<VERSION>-linux-<arch>.tar.gz`. The AppImage needs host Git; run it after `chmod +x`, or pass `--cli` to reach its bundled CLI. If FUSE is unavailable, set `APPIMAGE_EXTRACT_AND_RUN=1` when launching it. The tarball contains `./Ouroboros/bin/install-ouroboros-cli`. If bundled browser tools need host libraries, run `./Ouroboros/_internal/python-standalone/bin/python3 -m playwright install-deps chromium webkit` from the extracted tarball.

On a build host where system packages are managed separately, set `OUROBOROS_SKIP_PLAYWRIGHT_INSTALL_DEPS=1`; Chromium and WebKit are still downloaded and bundled, but the build does not invoke `sudo` to install host libraries.

### Linux (.deb and .rpm)

Wraps the payload `build_linux.sh` just produced, so run it afterwards:

```bash
sudo apt-get install -y dpkg-dev rpm   # rpm provides rpmbuild
bash scripts/build_linux_packages.sh
```

Output: `dist/ouroboros_<VERSION>_amd64.deb`, `dist/ouroboros-<VERSION>-1.x86_64.rpm` and `dist/ouroboros-<VERSION>-1.red80.x86_64.rpm` (RED OS 8). All three declare Git as a runtime dependency and install to `/opt/ouroboros` with a `/usr/bin/ouroboros` symlink, a desktop entry, and an opt-in systemd user unit. The Linux launcher is built by the bundled portable Python so the build runner cannot raise its glibc floor. `bash scripts/smoke_linux_packages.sh official <deb> <rpm> <red80-rpm>` installs all three through `apt` or `dnf` in Ubuntu 22.04 and Fedora 42 containers, resolves Git, verifies the installed unit, and checks both the real CLI and a bounded desktop-launcher start; this lane gates the release. Swap `official` for `vendor` to repeat the check on Astra Linux 1.8 and RED OS 8 images from the vendors' own registries — that lane runs informationally in CI, so an outage at a third-party registry cannot block a tagged release.

### Windows (.zip)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/download_python_standalone.ps1
powershell -ExecutionPolicy Bypass -File build_windows.ps1
```

Output: `dist\Ouroboros-<VERSION>-windows-x64.zip`, containing `Ouroboros\bin\install-ouroboros-cli.cmd`.


## Architecture and Runtime Data

The native launcher starts a web runtime and supervisor-managed agent workers. The agent core lives in `ouroboros/`, the builtin interface in `web/` (a replaceable client of the published contract in [`docs/CLIENT_CONTRACT.md`](docs/CLIENT_CONTRACT.md)), the process plane in `supervisor/`, and the runtime's durable identity, state, history, logs, and skills under `~/Ouroboros/data/`.

The full component map, data flow, API surface, storage layout, safety boundary, and operational rationale live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Deployment details live in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Runtime Commands

| Command | Purpose |
|---------|---------|
| `/panic` | Stop the runtime and its managed processes immediately. |
| `/restart` | Restart without automatically resuming the active owner task. |
| `/status` | Show workers, task queue, and budget state. |
| `/evolve on\|off` | Start or stop autonomous evolution. |
| `/review` | Queue a deep constitutional and architectural self-review. |
| `/bg start\|stop\|status` | Control background consciousness. |


## Philosophy

The 13 Constitution principles — Agency, Continuity, Meta-over-Patch,
Immune Integrity, Self-Creation, LLM-First, Authenticity & Reality
Discipline, Minimalism, Becoming, Versioning and Releases, the absorbed
Iterations / Spiral lineage, and Epistemic Stability — are defined in
full in [`BIBLE.md`](BIBLE.md). That file is the constitutional SSOT
(Bible P4 Ship-of-Theseus protection) and this README intentionally does
not paraphrase it.

---

## Contributing

External contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the complete agent-first workflow. Open pull requests against lowercase
`ouroboros`, leave release-version allocation to maintainers, and have a
separate agent context review the final diff. Any coding harness or configured
review route may produce the evidence; if none is available, record `NOT_RUN`
and the reason.

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 7.7.1 | 2026-10-20 | **fix: a start that serves before its repairs, the dialogue in SQLite, result review folded into ordinary review, one shell for desk, phone and Telegram, skills from a list of sources that can also extend the interface (dictation, Read aloud, living cards), context renewal instead of failure, and macOS packaging and notarization repairs.** Start-up opens the published current-facts store instead of re-importing every task result and child store, `/api/health` answers with a `boot` phase as soon as the socket opens, and the dialogue opens before background recovery; the desktop launcher waits for as long as the server process lives instead of stopping a start that has not answered within 60 seconds, and the CLI and Colab wait through the start phases (#1982). Chat and progress history move into `state/dialog.sqlite`: the first start stores the live files before it accepts a message, the archive is imported once in the background and kept, so history is stored in both, and history readers say it is still importing instead of showing an empty past; history-sized work runs in one low-priority maintenance process. A Rollback or update to a version without this store, 7.7.0 included, first exports the rows written since the move back to the files that version reads (#1982). Stores keep cached connections per thread instead of opening one per transaction, and use WAL when SQLite has the WAL-reset fix (3.51.3 or newer, or a backport) and the store is on a known local disk, otherwise a persistent rollback journal; WAL stores return to a rollback journal before another version takes the data folder. New desktop downloads and the Docker image ship python-build-standalone 20261009 (CPython 3.10.22, SQLite 3.53.1), so their local stores run in WAL; an in-app Update does not replace the interpreter, so an installation whose existing SQLite lacks the fix, including the observed 7.7.0 macOS interpreter with SQLite 3.50.4, stays on the rollback journal until the app is installed again (#1982). An empty queue write at start-up no longer erases saved Pauses, and Continue before the saved queue is restored answers `queue_not_restored` (#1952, #1982). Task acceptance is folded into ordinary review: `review_change(subject="result")` reviews a task's result under the same panel rules, and with task review set to Required the host runs one before a root delivers produced work; a PASS delivers, otherwise the findings are shown once, then Advisory and Cyber Pro deliver on Ouroboros's next decision while Blocking holds until a review passes or the task stops, and with task review Off none runs. The acceptance machine and its `OUROBOROS_ACCEPTANCE_REVIEW_EST_SEC` and `OUROBOROS_ACCEPTANCE_RESERVE_PCT` settings are retired, and no acceptance records are written any more while old ones still render; under Advisory a spent review allowance leaves to Ouroboros whether what was reviewed is enough, a review nobody waits for settles from the seats that answered, and Settings → Agents prices one review from a reviewer's recent reviews (#2029). The Reviewer tick now means whose agreement counts: for a change to Ouroboros's own code, a skill review or a first plan ask, Blocking seats every ticked reviewer and Advisory lets Ouroboros name fewer with a reason, an unticked reviewer it adds is heard as an adviser and never counted, and the review card shows who chose and each seat's cost (#2023). The managed Claudexor runtime moves from 4.2.0 to 4.3.1 (#1981, #2029). A task measures its next request against the last one its model accepted in that task; after a context-size refusal the host sheds superseded host state, review copies and shown tool bodies without a model call, and when nothing smaller fits it can continue the same task in a renewed view that keeps every delivered message, the outward dialogue and the task's own notes; the helper summarizer is removed, so `compact_context` needs the task's own note (#1996). The server now says what each work is doing (`works` and `rooms` in `/api/state`) for the room header, Shade, sidebar, cards and tray: Paused stays until Resume and says who paused it, a stopped work reads Stopped instead of Cancelled, each work row shows the focus line Ouroboros writes with `update_focus`, and a Continue held for its earlier attempt's helpers offers Stop earlier attempt and starts by itself once they settle; the owner's Pause ends post-answer upkeep at once instead of parking it, and the owner's Stop reaches the open delegated runs of a root that already ended, answering 202 while cancellation is unconfirmed, while a finished card keeps its tree's Stop (#1990, #2027, #2045, #2043). The web interface is one shell for desk, browser, phone and the Telegram Mini App, switching layout at 720 px: on a phone the sidebar is a drawer that follows the finger one to one from the edge, the header or the composer (where the system or Telegram owns the very edge, its gesture wins) and settles at the finger's speed, a message row swipes left to reply, a composer control's level strip opens in place, inside Telegram selected interactions give haptic feedback, a room's ☰ is the first control of its composer, Back, Escape, the scrim and × close what is on top first, and touch controls get a 44 px hit area; on a desk Main is pinned at the top of the sidebar with Projects and then the tools beneath it, page captions are gone, and the Project panel opens beside Main at its own width (#1998, #2000, #2001, #2003, #2035, #2038, #2052). Dragging a sidebar or panel edge restyles only the moved box, and feed rows far from view are laid out lazily while a width keeps changing (#2015); a desktop window that kept an older page no longer squeezes Main into a narrow column and its Projects list scrolls with the wheel again (#2008, #2040 by @josephsteuerjr); and Projects can be pinned from their ⋯ menu to sort first and stay visible when the list is collapsed (#2006 by @kazzand). Chat photos and delivered raster images open in the in-app reader, as do the owner's Markdown and text attachments (#2007 by @kazzand); a reply quote whose original is not loaded, or lives in another conversation, opens that conversation at the exact message (#1989); selected folders survive Project placement and Continue, and a work card keeps its earlier episodes' files and reviews (#1979); Settings reveals a secret in place, and Evolution reports a command that failed (#1983). Skills come from a list of sources: the Skills page has Installed, Browse and Sources, the public hub appears as Ouroboros (Official releases, suggested to install without review) and Ouroboros Community (suggested to review each), trust is chosen per source and recorded with each install, a first start offers starter skills by category, an update names its exact release and a review-each update that fails restores the previous version, and publishing uses the GitHub token from Settings instead of the `gh` CLI. Ouroboros can search for skills and install or update them with a stated reason, its own check in place of the configured review counts only in Cyber Pro (#2009), and a failed review no longer starts an automatic repair. The `/api/marketplace/ouroboroshub/*` routes except `GET …/installed` are retired in favour of `/api/skill-sources`, `/api/skill-catalog` and `/api/skills/{skill}/update`, `/uninstall` and `/publication/clear`. A one-time conversion binds the reviews, grants and attestations of unchanged skills to the new release identity; it is one way, so after a rollback to 7.7.0 converted skills need review and grants again (#1995). A bundled `windows_computer_use` skill reads windows on Windows as a text tree and acts on their elements through UI Automation, without screenshots, coordinate clicks or general keystrokes (#1776 by @josephsteuerjr). Computer use is on by default for the host's system, and so are four more bundled built-ins: `ui_design` and `design_demo` (instruction skills for visual work and for putting a visual choice before the owner as one page), `templates` (starter composer buttons and how to ask for your own) and `device_voice` (Read aloud); a new install's starter offers them ticked, and after this update an install that has made no on or off choice for one gets it installed and turned on when it is ready, while an owner's Off or removal stands (#1995, #1984, #2049). Skills can extend the interface where the host opens a place (#1984): a skill's buttons and live-value chips join the composer's "+" menu and capsule row and its actions join a saved reply's, drawn by the host from the skill's own label and a host glyph, an instruction skill can contribute buttons without code, and a trusted page module (a `page_module` grant) runs only through a small context and never draws into the composer or the feed; a module that fails is turned off for that page alone, a start that froze while modules started skips every module next time, and `?plugins=off` or Restart without plugins starts without them (`GET /api/ui/contributions` and `/api/ui/preferences`). Dictation and Read aloud are host controls over engines that skills provide: the composer has no mic until the owner picks a speech-to-text engine under "+" → Add dictation… (built-in Browser speech, free but not installed or on until chosen, whose audio the browser's vendor may hear, or Whisper from OuroborosHub), each engine names where audio goes, and dictation fills the draft and never sends; Read aloud reads one saved reply at a time with an engine on this device unless another is chosen, and the macOS app now declares microphone use and the Linux desktop window grants audio-only access to its own loopback page. Ouroboros can put a living card into its own message with `show_card` (components, a skill's widget or a sandboxed app, `card` history rows and `/api/cards/*`); component cards can be kept on Widgets with one press. A press on a card's control is delivered to the task that made it (or to the chat as the owner's own words once that task no longer reads mail), content handed back by an embedded app goes into the draft without sending, and Telegram and other surfaces get the card's plain words. Dashboard → Storage measures everything Ouroboros owns (data folder, program, engine home, working copies, Projects) in a low-priority background process with progress and Stop, keeps the finished count with its growth since the previous one, and shows unreadable places as unknown; Free space previews, then removes, finished tasks' folders and working copies whose task is proven over without the usual retention wait, so a task continued later starts without them. Working copies of ended tasks, review checkouts and unused Claudexor programs in `state/cx` retire on their own, artifact copies use block clones where the filesystem supports them, and workspace patches use transparent filesystem compression (#2004). Test runs before Ouroboros's own commits keep their complete output and an exact source recipe with the task, and nothing prunes them (#1976). Presence turns that went through review or chose to stop finish again instead of looping until they cancelled themselves, a Presence work view whose turn can no longer change answers `failed` instead of `unresolved` forever, saved Presence profiles that named renamed tools keep working, and the cap of two pending follow-ups per task is removed (#2011, #2016). Delegated agents start sooner because their private copies are filled in place (#1975), delegated sessions outside declared-input mode receive an index of eligible enabled instruction skills and are told not to modify host skills (#2049), acting children may ask `review_change` to review their own writable Git root (#1980), `inspect_subagent` reports a configured actor's route and dated quota facts and a granted extension skill can declare a `context_snapshot` for Main, Project roots and consciousness (#1981), and an ended model request with a recorded HTTP error no longer blocks Resume or Continue because its price is unknown (#2014). Web search progress names the sources that failed and the one that answered, vision tools pass on a typed provider error's own message, a declared output known to be invalid is refused before a command starts (#2020), refusals of Project files name the scoped tool that reaches them, and `pr_merge` keeps a PR's current state beside an earlier merge request that is still unresolved (#1986, #2019). Saved Vision and Consciousness choices, an empty one included, now take precedence over environment variables, so a blank saved by an older Settings form hides an operator's variable until it is removed; factory suggestions move direct Anthropic Main and deep review to Opus 5.5 and the Codex subscription preset to Sol 6.1 without changing saved choices (#2021). The bundled Telegram skill, now 1.3.4, keeps its typing indicator alive while a reply is being prepared (#1769 by @Timik232), adds the root task's cost to its opt-in completion notices (#1986), keeps the owner's message when its reply-reference map cannot be written (#1979) and counts message length faster (#2018). The macOS build drops pyobjc's debug-symbol bundles and test suite, which made Gatekeeper reject the 7.7.0 app as damaged, notarizes and staples the app before the DMG, and stops a signed stable release that Gatekeeper does not accept as notarized; a Mac that installed the 7.7.0 DMG needs the 7.7.1 DMG, because an in-app Update does not replace the app (#2010). A filesystem error in the optional log rotation, such as a Windows reader that denies rename sharing, is logged and retried on a later pass instead of failing the supervisor's pass (#1988 by @josephsteuerjr); on Windows, delegated-work and reviewer captures no longer leave `obo-payload-capture-*` folders in the temp directory (#2028), and release testing also fixed finished task folders that cached store handles kept from being deleted (#2022), skill-source probe clones left behind (#2022), a tracked WAL `-shm` index file that went into delegated copies and returned patches (#2042), and a Windows folder that Free space could not delete, which is now retried when maintenance next runs for other work (#2037). **Windows ordinary task-file, chat-media and result-ZIP downloads remain HTTP 503 (#1297).** |
| 7.7.0 | 2026-10-17 | **feat: current facts and spend move to SQLite, the managed Claudexor runtime reaches 4.2.0 with image generation, review uses one operation across supported subjects, plans become one living record with an explicit council, and working checkpoints retain saved work across Pause, Restart and crashes.** Task results, byte-exact bodies and obligations now live in one `state/current.sqlite`, and spend in `state/usage.sqlite` (#1733, #1537). The first start after the update imports the old files once, start-up and Restart stop re-reading the whole history, a read-only `query_data` tool answers questions over the install's state, and Dashboard gains a Storage tab (#1743); the store keeps its locks, closes descriptors with their last connection, and the evidence packer no longer starves model calls (#1752, #1760, #1756). Maintenance selects only current SQL work instead of re-reading settled history, and an ended attempt whose outcome is recorded is no longer polled for a price: an unknown cost stays unknown and its late receipt can still settle it (#1826). **The import is one way:** before rolling back to 7.6.0, export spend with `scripts/export_usage_journal.py` and current facts through the store-switch procedure; reviewer settings return from their migration snapshot; Claudexor engine state is forward-only, and 4.2.0 also migrates the engine store from schema 1 to 2: a body pinning 4.1.x, automatic boot-smoke rollback included, leaves Claudexor-backed routes unavailable until 4.2.0 or newer returns or a complete pre-update backup of `DATA_DIR/claudexor/` and `~/.cache/claudexor/`, taken with Ouroboros stopped, is restored. The managed Claudexor runtime moves from 3.20.1 to 4.2.0 (#1558, #1665, #1669, #1670, #1673, #1740, #1758, #1627, #1896): engine state moves to SQL with a one-time import of old run journals shown in the Accounts banner, delegated runs continue in place, Accounts shows harness versions with Update, resource and reset controls, model waits show their real phase, and Ouroboros sends far fewer engine requests (#1702, #1691, #1638). A `generate_image` tool creates and edits images with gpt-image-2 through a connected ChatGPT/Codex account (#1627 by @josephsteuerjr). Review uses the same operation machinery across supported subjects: durable review records (#1622), `review_change` for any root (#1625), reviewers as catalog rows with a one-time migration of the old review lanes (#1639), and isolated investigation copies (#1726); self-changes are authored in an isolated body candidate (#1620). Native reviewers manage their own context with no fixed character ceiling and no round cap, and the model's window facts are evidence for them, not a send limit; the provider window, the owner's deadline and the paid ledger remain the bounds (#1810). Review and delegated-work captures now store file bytes exactly as they are on disk through one Git writer instead of a Git process per file, so line-ending and `.gitattributes` filters cannot alter what is reviewed; an index readback refuses capture when Git silently omits a requested path instead of reporting success over incomplete work (#1807, #1824). One-shot reviewer copies now live only for their review: evidence is captured before removal even after a failed run; an unreadable capture leaves the copy to the pruner, thread copies keep their existing lifecycle, and ordinary task folders are read in place (#1963, #1968, #1970, superseding #1883). Plans have one living record per task (#1815, with @josephsteuerjr): revisions of the goal, `done_when` claims, affected files and plan do not call reviewers; an explicit ask sends the current revision to selected participants. Under Blocking outside Cyber Pro, outstanding reviewer objections may hold normal finalization, and only their raiser withdraws them. Acceptance uses explicit task-contract claims, otherwise the latest `done_when`; earlier records remain readable, pending replies never imply approval, and old-form calls name the new interface. Without marked reviewers, Main reviews alone with that limitation disclosed. Under Advisory and Cyber Pro, commit review returns its complete result to the author before commit, tag or push. Task acceptance also preserves the paid review it already has: an informed Advisory finish is judged against the exposed feedback and current evidence without requiring a separate rationale; author and critic subjects remain distinct (#1813). Pause stops the author's own work, and a working checkpoint restores saved cognition up to its last recorded boundary across Restart, update, Quit and process crash; interrupted tool calls without recorded results remain unknown and are not replayed, and power-loss durability is not promised (#1689, #1694); Resume keeps its governing state across application stops (#1762), Continue keeps its first context (#1768), and Resume lineage and Continue over damaged plan sources are repaired (#1592, #1746). Automatic retries retain the owner's Pause and Stop (#1898); unreadable budget or control authority preserves work in a technical Pause awaiting the owner's explicit Resume rather than claiming exhausted funds (#1901), while confirmed temporary SQLite contention during a Pause check waits in place (#1902). Unavailable recovery observations preserve saved work (#1917). Continue excludes independent reviewers from its writer census while Resume retains the full custody check; ended local owners require positive evidence, and an explicit continuation can accept a finished native helper's saved product without inheriting live control (#1947). One execution clock now bounds every finite run: queue time before the first dispatch, confirmed quota waits, Pause and model sleep do not count, tool time does, and calendar deadlines never move (#1786). A model call proven never to have started, including a Claudexor not-started receipt, is released at $0, configured alternatives run first, and an interruptible network wait with truthful outage text follows; a task that has already failed reads Failed · Finalizing while it wraps up (#1785). Completed delegated work can wake its owner before accounting and file capture finish, slow workspace preparation no longer blocks owner controls, and ordinary tool claims and retained result delivery recover from confirmed transient storage contention (#1817, #1820); unsent helper admission and delegated-start receipts retain their identity through confirmed store contention, without replaying a sent request (#1821, #1822); an inapplicable learned parameter removal no longer disables effort recovery (#1819). Completion delivers its retained answer before accounting and capture finish; recovery finalizes a recorded answer without replaying the answered prompt, and pool growth and shutdown preserve unresolved work (#1872, #1877). Lessons, patterns and the improvement backlog are authored through the knowledge writer; automatic post-task reflection and backlog rewriting are removed, with earlier records retained (#1866). Each tool call has one invocation owner: joined calls share the real execution and its lifetime, external effects keep durable custody, and a registration proven unsent is cleaned up (#1825). Ouroboros can author its own working context, restore exact sources and share its story across rooms (#1690, #1703, #1708); knowledge archiving is reversible (#1664). Earlier attributed accounts retain their periods and correction provenance, without claiming summarization is lossless (#1897). Retelling instructions preserve the source-supported situation, purpose and scope of decisions for the next reader; a proposal is not approval and a helper's retelling remains an attributed draft (#1923). Presence keeps the exact incoming event context, such as supplied thread history, reachable through `memory_read(source_ref=...)` (#1890). Context targets never cut a read Ouroboros chose or the owner's words, and memory already shown is kept across a route change that still fits (#1829). Helpers keep their selected predecessor briefs, long-line search exposes match-centred readable ranges, and `query_data` names its source plane under the caller's existing read permissions (#1880). Tasks see host facts (money bounds, clocks, tool counts and crossed thresholds) instead of periodic strategy advice; a completed check whose criterion failed is shown as its own warning, not as a failed call; background consciousness wakes on its own schedule, not on task events (#1830). The composer pairs Context and Effort capsules (#1763) with room-local choices: Main seeds new Projects once, the primary effort is independent of the helper bounds, and new participants use their room's current values while existing actors retain theirs through Resume (#1941); a room opening with unread messages lands on the latest arrival (#1764), and a Project room whose newest unread message lies beyond its first loaded page reads older pages until it reaches that message instead of stopping short (#1806). Project cards and Project references are lighter, with the Project mark on a soft tinted tile and clearer navigation (#1783, #1787), and helper labels name the actor and reserve secondary wording for exceptions (#1808). Main and Project headers expose room work without taking over execution (#1876, #1878); selecting work can load its surrounding history, with Back to reading returning to the prior passage (#1957). System notices do not end unrelated Working or Sending states, and model-created roots need short titles (#1893). New work, moving work to a Project and relaying owner words have separate verbs: `start_task`, `move_to_project` and `tell_task`. Relays keep selected owner words and attachments separate from the agent's note and carry a return address and read acknowledgement. A moved work keeps one Main portal, and Continue episodes share its card rather than multiplying entries (#1959); titles no longer accumulate Continue prefixes (#1774). Unanswered Project questions remain reachable until answered or closed with a reason, and complete outcomes and retained files stay reachable after timeline eviction (#1899). Main uses the same answerable question card as the Project, with narrow-screen wrapping and one composer pill for off-screen questions or actions rather than a separate Needs you section (#1930, #1946). Long mirrored results retain their fold, Copy and Project link without an in-place Show full or Files inventory (#1925). Room history skips a closed archive only when its summary rules that room out (#1954). Attachments render in one durable message with manual retry (#1594), images reach a running task (#1680), delivered documents open in an in-chat reader (#1595), and notifications use the operating system (#1596). The whole web interface is a replaceable client of the core's published HTTP and WebSocket contract (`GET /api/contract`, [`docs/CLIENT_CONTRACT.md`](docs/CLIENT_CONTRACT.md)): the main-interface setting (Settings → Advanced, applied on restart) serves the builtin interface, a trusted directory, or nothing for a separately hosted one, and saved interface choices survive unrelated settings saves (#1828). A selected directory may supply complete setup and sign-in pages while authentication and control remain in the core; absent or unreadable optional pages fall back to builtin, explicit builtin recovery URLs remain available, and updated macOS launchers add Help → Open built-in setup independently of page JavaScript (#1938); a locally edited custom interface is not yet natively qualified through Update and Restore from an older desktop bundle. Deployments can choose where the install lives and run a persistent managed container (#1767); container PID 1 launches and the Telegram companion retain the real spawner identity, without treating later orphan adoption as a legitimate parent (#1780); automatic model defaults refresh without overwriting saved choices (#1765); Docker workspaces resolve the same files for file and process tools (#1761). Task completion triggers scope cleanup for commands and non-kept services on local POSIX backends (#1896), with disclosed gaps for hidden scope markers and children left uncaptured after shell exit; this binding reports `unsupported` on Windows and for Docker-executor children, and native Linux qualification is not claimed. File edits are atomic and source-aware (#1636 by @kazzand), the skill catalogue is compact (#1624 by @kazzand), MCP servers gain protected headers and `mcp.json` import (#1637 by @kazzand), image input follows the route's own evidence (#1542) and Z.ai is the vision default (#1560 by @josephsteuerjr). New macOS desktop bundles integrate the page with the native title bar and traffic lights; undeclared custom pages keep ordinary window chrome (#1971, proposed by Yan). Older bundles may still reopen their frozen shell after a source-only update, so the new window design needs the new desktop installer. Windows gets a dark title bar (#1590 by @josephsteuerjr), a signed release ZIP when the repository's signing is configured (#1495 by @kazzand), and a direct-mode restart that hands over to its successor (#1500 by @kazzand); wrapped interaction answers keep their outcome (#1646 by @jipeng6036-del). Release testing also fixed `query_data` and evidence packing on Windows, review checking that reported every unchanged symlink as reviewer work on Windows, a model call that failed when a queue publication raced its spend reservation or dispatch, a Resume that opened the pause fence while a late acceptance review was reading its controls, End and PageDown stopping short in WebKit, and composer capsules that laid out inside a resize notification; the Windows test leg now runs in four shards with a completeness proof that distinguishes subtests from repeated executions. Official-skill checks retain their review history and do not retry unsettled reviewer work (#1778). Later qualification corrections retain full assertions while making test-fixture path and byte assertions portable and preserving the Windows-cased launch key and limiting shutdown diagnostic locking to the remaining grace (#1900, #1906, #1914). The assisted updater again reads real reviewer routes before resolver launch (#1916, diagnosed by @ndrew1337). Telegram's existing completion-notice toggle becomes a true opt-out (#1915, seed 1.2.14): Off, including previously saved Off values, suppresses all additional completion notices, failures and cancellations included, and notices observed while Off are not replayed later; replies, files and questions remain independent, and functional failure causes remain visible when notices are enabled. Release qualification runs required and optional providers separately: an optional provider failure stays red and sits outside the mandatory release bar, while every required canary must pass; Cloud.ru GLM-4.7's retained tool-argument contract failure (#1429) is of this kind, not an adapter fix. Desktop build recipes install the locked desktop dependencies into the embedded source-handoff interpreter, and final DMG, Linux archive and Windows ZIP checks exercise those imports without opening a GUI (#1958); these checks do not qualify native GUI transitions or replace installer, signing and provenance proof. Ordinary cloud CI no longer starts on branch pushes or PRs: manual and release-tag qualification remain, including their mandatory release dependencies, while local tests and independent review continue (#1961). Also from the community: @deebosh (#774, #782), @kerreli24-lang (#1474), @josephsteuerjr (#1561), @kazzand (#1623). **Windows ordinary task-file, chat-media and result-ZIP downloads remain HTTP 503 (#1297).** |
| 7.6.0 | 2026-10-05 | **feat: memory as one ladder, one interface language for the whole install, and a desktop that can start at sign-in and keep running in the background.** Memory keeps an open conversation verbatim, turns a closed matter into an authored page whose quotations are checked against the conversation, and keeps pages, notes and corrections in an append-only journal (#1496, #1507, #1480). The old dialogue memory is imported once, without a model call, when the new memory is first used or at startup when its notice is due, then folded gradually, with a one-time notice in the owner's chat. The import is one way: rolling the code back to 7.5.1 does not bring back what the new memory recorded after the update, while chat history, scratchpad and knowledge stay readable. One interface language for the web UI, the desktop window and Telegram comes from a translation memory that the install's own light model fills; the repository ships no dictionary and untranslated strings stay English (#940, contributed by @Fgeeha). Settings → Behavior → Startup & background adds two opt-in choices: start at sign-in on Windows, macOS and Linux, and, on Windows and macOS, keep running after the window closes, with a tray icon or a menu-bar item (#1405, #1404, contributed by @josephsteuerjr); keeping it running needs the 7.6.0 desktop installer, and Settings says when sign-in start needs a newer installer or Linux package. Tasks gain Pause, Resume and Continue, and the model can put a waiting task to sleep (#1442, #1505); an outage of one Project no longer rejects valid work (#1441, #1447); configured fallback models take over after an access refusal or a lost response (#1443); Nano works: its 85K target sizes the input while each reply is sized from the route's known window, and an empty reply cut at its length limit becomes a fact for the next round instead of retries and a false provider outage (#1526); task trees exchange mail and declared inputs, helpers can read what their parent can, and their isolated Git copies carry the parent's uncommitted work (#1475, #1394, #1431). Skills can notify the owner without a model turn, and a Project root can send a short notice to Main (#1337 by @kazzand, #1416). Every room opens at its newest message and loads only its own older history (#1513, #1415); the Skills page, Settings and chat history no longer wait on queue locks or repeated full reads (#1514); Enter submits an answer (#1384); long Markdown keeps its headings, tables and code fences (#1437). Update letters cover the whole range since the running server started, and a managed update restores local work automatically, or keeps it in a stash with a recovery notice when it cannot (#1494, #1499); a Panic stop survives automatic starts (#1479, #1486). The Widgets page becomes an owner-arranged board (#1438 by @kazzand); Settings can reveal a complete saved secret (#1478); a stored 0 survives the Settings form (#1238, @pandakononov); the managed Claudexor runtime moves from 3.16.0 to 3.20.1 (#1414, #1450, #1208 with @kzmx23, #1484, #1508). `run_ci_tests` is replaced by the read-only `get_github_checks`; new tools are `memory_read`, `chronicle_write`, `memory_mark`, `finish_task` and `pr_merge` (#1466, #1496, #780 by @deebosh, #1392). Installs without a saved reviewer panel now run reviewers that read the work themselves with read-only tools, which takes several model calls per review instead of one packet (#1392); review, delivery and cost reporting stay truthful through late acceptance, merge evidence and ledger compaction (#1359, #1392, #1395, #1361, #1433, #1509). A direct-mode server on Windows now restarts through a supervised successor instead of the C runtime's emulated exec (#1522). Every process now logs with secret redaction and records unexpected failures with their stack (#1529), and on Windows a model call no longer fails as a permission error while another worker releases the usage-accounting lock (#1532). Also from the community: @deebosh (#755, #772, #781, #783), @ndrew1337 (#1117, #1237), @SEVENID (#1146, and a Telegram-only proxy setting in #1149), @cstolting-collab (#1161). **Windows ordinary task-file, chat-media and result-ZIP downloads remain HTTP 503 (#1297).** |
| 7.5.1 | 2026-09-26 | **fix: resumable work, planning dialogue and reliable results.** Changes since 7.4.11 preserve tasks through budget pauses, reviewer answers through follow-ups, child files and unread messages through cleanup, and unedited memory with its source history. Includes responsive owner controls, Presence recovery, Claudexor 3.16.0 live messaging, provider caching and Docker/TLS improvements, plus portable CI and Python 3.13 repairs. **Windows ordinary task-file, chat-media and result-ZIP downloads remain HTTP 503 (#1297).** |
| 7.5.0 | 2026-09-26 | **feat: one self-contained Docker image and an owner extra-CA bundle for provider TLS (#1300).** Contributed by @komsikov and reworked in-branch: the image installs the locked Playwright browsers above the lock copy with BuildKit cache mounts (4.82 GB → 4.12 GB; the tag-only docker lanes exercise the shipped browsers), and `OUROBOROS_EXTRA_CA_BUNDLE` adds a PEM of extra CA certificates on top of certifi for every first-party provider call, with a content-addressed merged bundle so a rotated certificate takes effect on the next task (Settings → Advanced; `docs/DEPLOYMENT.md`). |
| 7.4.11 | 2026-09-24 | **chore: ignore `graphify-out` and add a root `.dockerignore` (#1255).** Contributed by @komsikov; the Docker build context keeps secrets, host environments and local runtime/review state out of image layers while `.git`, `tests/` and sources stay in, pinned by `TestDockerignore`. |
| 7.4.10 | 2026-09-24 | **fix: isolate candidate verification and run complete event-driven browser CI (#1215, #1143, #1084, #1112).** Tests, preflight and server children run on disposable HOME/data/projects/worktrees/Deliverables roots and never install dependencies into the operator's Python; a browser candidate is a faithful copy of the dirty tree (staged, unstaged, new, deleted, binary, mode) whose source HEAD, index and files are proven unchanged, with unsupported inputs and concurrent mutation refused explicitly and temporary trees retained until process teardown is proven. The complete existing `ui_browser` lane runs for every non-documentation PR and every `ouroboros` push through `--require-ui-browser` (no new cron); the startup history-audit child inherits the containment token; the isolation keeps the platform's default text encoding so Windows CI still catches cp1252 bugs. |
| 7.4.9 | 2026-09-24 | **fix: truthful task cards and history (#1011, #1087, #1110, #1154, #1061, #931, #1073, #516, #869, #498).** A known outcome (Failed / Done with warnings) is the card's primary word while post-task work still runs, with `Finalizing…` secondary and the task name stable; a completed lifecycle with a failed outcome never reads as a clean completion. Money speaks one scoped carrier — `Cost unknown`, `Tracked: $X`, `up to $X`, an evidenced `$0.00` — with `cost unavailable` reserved for an unreadable ledger and a nested child's foreign rollup never replaced by its own zero. Cancellation states its recorded cause and proven parent relation; task diagnostics stay in the disclosure, worker events in Logs; the Project's final Main summary is durably owed, retried and deduplicated after completion, and the provider-outage terminal names its source and a human cause without extra model calls. Verified by focused, Node and real-backend browser journeys including a live Failed+Finalizing actor. |
| 7.4.0 | 2026-09-20 | **feat: add an honest desktop attention cue for live notifications.** The optional launcher bridge can raise the existing desktop window and request one platform system sound, returning explicit native/unsupported/window_only/unavailable facts; it does not claim Notification Center delivery, run after close, or add a tray/background process. Browser banners and in-app toasts remain the fallback, with capability text visible in Settings. Focused native, launcher and notification tests cover the seam. |
| 7.3.0 | 2026-09-19 | **feat: notifications can pull you back to a question or a finished task while a client is running (#1122).** Settings → Appearance gains a notification block next to the theme: a master switch, the two required categories (a question or decision is waiting for you, a task finished or stopped), a model-chosen category for messages Ouroboros sends while it works, a separate off-by-default toggle for ordinary replies in Main, sound, an off-by-default show-the-text choice and a test notification. The choices are stored per client exactly like the appearance choice, never reach the server, and do not make the settings draft dirty. Delivery is page-level: a system banner where this client exposes one and permission is granted, otherwise the in-app surface plus one short tone, with the status line saying which surface you actually have; either way a click opens the source. The new `web/modules/notifications.js` keeps classification and the delivery gate pure over one live frame plus the stored preferences, and takes ONE subscription per client on the shared socket — not inside a chat instance, which dies with its room, so a Project the owner never opened still reaches him; `web/modules/chat.js` is untouched. Only live frames reach it, so a reload cannot re-notify without any stored notification state. A finished managed root is recognised on the shape it actually arrives in (a live `task_done` log frame) as well as the authored summary, and a conversation turn's own ending stays the ordinary-reply category instead of claiming a task finished; all of them collapse to one key per task. A child task never notifies the owner: it escalates to its parent, and lineage is read from the delegation facts frames carry because the terminal frame has none. Importance needs no new host field and no second model call: the existing proactive-message discriminator is the signal. Policy and its disclosed limits have one canonical home in `docs/DESIGN.md` §9 — including that each open window is its own client, that an event during a dropped socket never rings, and that no OS permission, Do Not Disturb or platform limit is bypassed. |
| 7.0.0 | 2026-09-08 | **v7: a modular runtime with full ordinary-conversation tools, complete delegated inputs and visible owner dialogue.** Main and Project conversations retain their chosen tools and working folders; required owner waits preserve the live browser without occupying pooled execution capacity. Publish admission is visible in its intended chat, and GitHub/image/plan failures retain their actual causes. Planning advice stays optional; source-backed evidence, separate host notices and exact-workload test reuse preserve honest review without new approval machinery. Integrates the subscription model and account-role controls, owned startup/restart custody and cross-platform repairs, with Claudexor pinned to 3.10.1. |
Older releases are preserved in this repository's history. Rows 7.2.0, 7.1.0, 7.4.7, 7.4.5, 6.114.0, 6.113.2 and 6.113.5 are retained in Git history. Older 6.x rows (including 6.113.1, 6.110.0, 6.109.0, 6.110.1, 6.108.1, 6.106.0, 6.101.1, 6.97.2, 6.105.0, 6.97.1, 6.97.0, 6.96.1, 6.96.0, 6.95.0, 6.94.0, 6.93.0, 6.92.1, 6.92.0, 6.91.1, 6.90.3, 6.91.0, 6.90.2, 6.90.0, 6.87.5, 6.87.4, 6.87.3, 6.87.2, 6.84.0, 6.87.1, 6.83.0, 6.86.1, 6.81.1, 6.76.0, 6.75.0, 6.74.5, 6.74.4, 6.74.1, 6.74.0, 6.73.2, 6.73.1, 6.73.0, 6.72.0, 6.71.2, 6.71.1, 6.71.0, 6.70.0, 6.69.0, 6.68.0, 6.67.0, 6.66.0, 6.65.4, 6.65.3, 6.65.2, 6.65.1, 6.65.0, 6.64.3, 6.64.2, 6.64.1, 6.64.0, 6.63.0, 6.62.0, 6.61.4, 6.61.3, 6.61.1, 6.61.0, 6.60.0, 6.59.0, 6.58.0, 6.57.0, 6.56.0, 6.55.0, 6.54.4, 6.54.2, 6.54.1, 6.54.0, 6.53.4, 6.53.0, 6.51.0), the 5.2.0 through 5.33.0-rc.6 rows, and former `4.0.0` rows are rolled off to respect the P9 changelog cap; their full bodies remain in this file's git history, with release tags where present for historical versions.

---

## License

[MIT License](LICENSE)

Created by [Anton Razzhigaev](https://t.me/abstractDL) & Andrew Kaznacheev

Thanks to [Praxis Relay](https://github.com/josephsteuerjr/praxis-relay) and
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) for the open-source
ideas and implementations that informed Ouroboros's subscription-backed model
transport through Claudexor.
