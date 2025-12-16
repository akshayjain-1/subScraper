# Recon Command Center

Recon Command Center is a single-file orchestrator for common reconnaissance pipelines. It runs traditional subdomain enumeration tools, probes discovered hosts, and executes vulnerability scanning workflows while presenting live progress in a rich web UI.

## Highlights

- **Full pipeline automation** – Amass/Subfinder/Assetfinder/Findomain/Sublist3r feed ffuf, httpx, screenshot capture, nuclei, and nikto in one go.
- **Stateful & resumable** – Results live in `recon_data/state.json`, so re-running a target picks up exactly where it left off. Jobs can be paused/resumed live.
- **Live dashboard** – A modern SPA served from `main.py` tracks jobs, queue, worker slots, tool availability, and detailed per-program reports.
- **Actionable reports** – Each target gets a dedicated page with sortable/filterable tables, paginated views, per-tool sections, command history, severity badges, and a progress overview.
- **Command history & exports** – Every command executed is logged; you can export JSON or CSV snapshots at any time.
- **Monitors** – Point the UI at a newline-delimited URL (supports wildcards like `*.corp.com` or `corp.*`). The monitor polls the file, launches new jobs when entries appear, and surfaces health/status in its own tab.
- **Concurrency controls** – Configure max running jobs and per-tool worker caps so scans behave on your box.
- **Auto-install helpers** – Best-effort installers kick in when a required tool is missing.

## Usage

```bash
# Launch the web UI (default: http://127.0.0.1:8342)
python3 main.py

# Run a one-off target directly from the CLI
python3 main.py example.com --wordlist ./w.txt --skip-nikto

# Wildcards are supported
python3 main.py 'acme.*'        # expands using Settings ➜ wildcard TLDs
python3 main.py '*.apps.acme.com'
```

Inside the UI you can:

1. Launch new jobs from the Overview module.
2. Pause/resume running jobs in the Jobs module.
3. Inspect tool/worker utilization in Workers.
4. Drill into the revamped Reports page to see per-program progress, completed vs pending steps, collapsible per-tool sections, paginated tables, and the max-severity badge.
5. Configure monitoring feeds under the Monitors tab – each monitor shows polling health, last fetch, number of pending entries, and per-entry dispatch status.
6. Export raw data or tweak defaults in Settings (concurrency, wordlists, skip flags, wildcard TLD expansion, etc.).

All output (jsonl history, tool artifacts, screenshots, monitor metadata) lives under `recon_data/`, making it easy to version, sync, or analyze with other tooling.

## Development Notes

The project intentionally stays self-contained:

- Everything (scheduler, API server, UI) lives in `main.py`.
- No third-party web framework; the UI is rendered client-side with vanilla JS/HTML/CSS embedded in the script.
- Concurrency is managed with Python threads and lightweight gates (`ToolGate`) to keep tool usage predictable.
- State files are protected with a simple file lock to avoid concurrent writes.

### Helpful Commands

```bash
# Format / validate
python3 -m py_compile main.py

# Inspect current jobs / queues
curl http://127.0.0.1:8342/api/state | jq

# Export recent command history for a program
curl 'http://127.0.0.1:8342/api/history/commands?domain=example.com'
```

Feel free to tailor the pipeline order, add custom steps, or integrate additional tooling. Contributions welcome!
