#!/usr/bin/env python3
"""
Recon Orchestrator

Features:
- Input: TLD / domain
- Tools: amass, ffuf, httpx, nuclei, nikto
- Auto-install (best effort) if tools are missing
- Optional Amass API key setup on first run
- Subdomain enumeration (amass + ffuf brute)
- Dedup + stateful JSON DB for progress/resume
- HTTP probing (httpx)
- Vuln scanning (nuclei, nikto)
- One shared HTML dashboard updated every N seconds
- Safe to run multiple times concurrently on the same machine
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# ====================== CONFIG ======================

DATA_DIR = Path("recon_data")
STATE_FILE = DATA_DIR / "state.json"
HTML_DASHBOARD_FILE = DATA_DIR / "dashboard.html"
LOCK_FILE = DATA_DIR / ".lock"

HTML_REFRESH_SECONDS = 30  # default; can be overridden by CLI

# Tool names (can be adjusted per OS if needed)
TOOLS = {
    "amass": "amass",
    "ffuf": "ffuf",
    "httpx": "httpx",
    "nuclei": "nuclei",
    "nikto": "nikto"
}


# ================== UTILITIES =======================

def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} UTC] {msg}")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def acquire_lock(timeout: int = 10) -> None:
    """
    Very simple file lock; best-effort to avoid concurrent writes.
    """
    start = time.time()
    while True:
        try:
            # use exclusive create
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            if time.time() - start > timeout:
                log("Lock timeout reached, proceeding anyway (best effort).")
                return
            time.sleep(0.1)


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "version": 1,
            "targets": {},
            "last_updated": None
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Error loading state.json: {e}")
        return {
            "version": 1,
            "targets": {},
            "last_updated": None
        }


def save_state(state: Dict[str, Any]) -> None:
    state["last_updated"] = datetime.utcnow().isoformat()
    acquire_lock()
    try:
        tmp_path = STATE_FILE.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        tmp_path.replace(STATE_FILE)
    finally:
        release_lock()


def ensure_tool_installed(tool: str) -> bool:
    """
    Best-effort install using apt, then brew, then go install (for some tools).
    Returns True if tool is available after this, False otherwise.
    """
    exe = TOOLS[tool]
    if shutil.which(exe):
        log(f"{tool} already installed.")
        return True

    log(f"{tool} not found. Attempting to install (best effort).")

    # Try apt
    try:
        if shutil.which("apt-get"):
            log(f"Trying: sudo apt-get update && sudo apt-get install -y {exe}")
            subprocess.run(
                ["sudo", "apt-get", "update"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", exe],
                check=False,
            )
            if shutil.which(exe):
                log(f"{tool} installed via apt-get.")
                return True
    except Exception as e:
        log(f"apt-get install attempt failed for {tool}: {e}")

    # Try Homebrew
    try:
        if shutil.which("brew"):
            log(f"Trying: brew install {exe}")
            subprocess.run(
                ["brew", "install", exe],
                check=False,
            )
            if shutil.which(exe):
                log(f"{tool} installed via brew.")
                return True
    except Exception as e:
        log(f"brew install attempt failed for {tool}: {e}")

    # Try go install for some known tools
    try:
        if shutil.which("go") and tool in {"amass", "httpx", "nuclei"}:
            go_pkgs = {
                "amass": "github.com/owasp-amass/amass/v3/...@latest",
                "httpx": "github.com/projectdiscovery/httpx/cmd/httpx@latest",
                "nuclei": "github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest",
            }
            pkg = go_pkgs[tool]
            log(f"Trying: go install {pkg}")
            subprocess.run(["go", "install", pkg], check=False)
            if shutil.which(exe):
                log(f"{tool} installed via go install.")
                return True
    except Exception as e:
        log(f"go install attempt failed for {tool}: {e}")

    log(
        f"Could not auto-install {tool}. Please install it manually and re-run. "
        f"Checked binary name: {exe}"
    )
    return False


# ================== AMASS CONFIG ==================

def ensure_amass_config_interactive() -> None:
    """
    If no amass config is found, optionally ask user if they want a basic template
    and (optionally) enter some keys.
    """
    config_dir = Path.home() / ".config" / "amass"
    config_file = config_dir / "config.ini"

    if config_file.exists():
        return

    log("No Amass config.ini found (~/.config/amass/config.ini).")
    try:
        ans = input("Do you want to generate a basic Amass config and optionally enter API keys? [y/N]: ").strip().lower()
    except EOFError:
        # Non-interactive case, just skip
        return

    if ans != "y":
        log("Skipping Amass API key setup.")
        return

    config_dir.mkdir(parents=True, exist_ok=True)

    # Ask optionally for some keys
    providers = {
        "shodan": None,
        "virustotal": None,
        "securitytrails": None,
        "censys": None,
        "passivetotal": None,
    }

    log("Press Enter to skip any provider.")
    for name in list(providers.keys()):
        try:
            key = input(f"Enter API key for {name} (or leave blank): ").strip()
        except EOFError:
            key = ""
        providers[name] = key or None

    # Write basic config.ini
    lines = [
        "# Generated by recon_dashboard.py",
        "[resolvers]",
        "dns = 8.8.8.8, 1.1.1.1",
        "",
        "[datasources]",
    ]
    for name, key in providers.items():
        if key:
            lines.append(f"    [{name}]")
            lines.append(f"    apikey = {key}")
            lines.append("")
        else:
            # add commented stub
            lines.append(f"    #[{name}]")
            lines.append("    #apikey = YOUR_KEY_HERE")
            lines.append("")

    config_file.write_text("\n".join(lines), encoding="utf-8")
    log(f"Amass config created at {config_file}. You can tweak it later if needed.")


# ================== PIPELINE STEPS ==================

def run_subprocess(cmd, outfile=None):
    log("Running: " + " ".join(cmd))
    try:
        if outfile:
            out = open(outfile, "w", encoding="utf-8")
        else:
            out = subprocess.DEVNULL

        result = subprocess.run(
            cmd,
            stdout=out,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

        if outfile:
            out.close()

        if result.returncode != 0:
            stderr_preview = (result.stderr or "")[:500]
            log(
                f"Command failed (return code {result.returncode}): "
                + " ".join(cmd)
                + "\nstderr: " + stderr_preview
            )
            return False

    except FileNotFoundError:
        log(f"Command not found: {cmd[0]}")
        return False

    except Exception as e:
        log("Error running command " + " ".join(cmd) + f": {e}")
        return False

    return True


def amass_enum(domain: str) -> Path:
    """
    Run Amass enum with JSON output and return path to JSON file.
    """
    if not ensure_tool_installed("amass"):
        return None

    ensure_amass_config_interactive()

    out_json = DATA_DIR / f"amass_{domain}.json"
    cmd = [
        TOOLS["amass"],
        "enum",
        "-d", domain,
        "-oA", str(out_json),
    ]
    success = run_subprocess(cmd)
    return out_json if success and out_json.exists() else None


def parse_amass_json(json_path: Path) -> List[str]:
    subs = set()
    if not json_path or not json_path.exists():
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    name = obj.get("name")
                    if name:
                        subs.add(name.strip().lower())
                except Exception:
                    continue
    except Exception as e:
        log(f"Error parsing Amass JSON: {e}")
    return sorted(subs)


def ffuf_bruteforce(domain: str, wordlist: str) -> List[str]:
    """
    Use ffuf to brute-force vhosts via Host header.
    This is HTTP-based vhost brute, not pure DNS brute, but still useful.
    """
    if not ensure_tool_installed("ffuf"):
        return []

    out_json = DATA_DIR / f"ffuf_{domain}.json"
    # NOTE: user can tune -mc, -fs, etc to avoid wildcard noise.
    cmd = [
        TOOLS["ffuf"],
        "-u", f"http://{domain}",
        "-H", "Host: FUZZ." + domain,
        "-w", wordlist,
        "-of", "json",
        "-o", str(out_json),
        "-mc", "200,301,302,403,401"
    ]
    success = run_subprocess(cmd)
    if not success or not out_json.exists():
        return []

    subs = set()
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            host = r.get("host") or r.get("url")
            if host:
                # ffuf may show host as FUZZ.domain.tld
                host = host.replace("https://", "").replace("http://", "").split("/")[0]
                subs.add(host.lower())
    except Exception as e:
        log(f"Error parsing ffuf JSON: {e}")
    return sorted(subs)


def write_subdomains_file(domain: str, subs: List[str]) -> Path:
    out_path = DATA_DIR / f"subs_{domain}.txt"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            for s in sorted(set(subs)):
                f.write(s + "\n")
    except Exception as e:
        log(f"Error writing subdomains file: {e}")
    return out_path


def httpx_scan(subs_file: Path, domain: str) -> Path:
    if not ensure_tool_installed("httpx"):
        return None
    out_json = DATA_DIR / f"httpx_{domain}.json"
    cmd = [
        TOOLS["httpx"],
        "-l", str(subs_file),
        "-json",
        "-o", str(out_json),
        "-timeout", "10",
        "-follow-redirects",
        "-silent",
    ]
    success = run_subprocess(cmd)
    return out_json if success and out_json.exists() else None


def nuclei_scan(subs_file: Path, domain: str) -> Path:
    if not ensure_tool_installed("nuclei"):
        return None
    out_json = DATA_DIR / f"nuclei_{domain}.json"
    cmd = [
        TOOLS["nuclei"],
        "-l", str(subs_file),
        "-json",
        "-o", str(out_json),
        "-silent",
    ]
    success = run_subprocess(cmd)
    return out_json if success and out_json.exists() else None


def nikto_scan(subs: List[str], domain: str) -> Path:
    if not ensure_tool_installed("nikto"):
        return None
    out_json = DATA_DIR / f"nikto_{domain}.json"

    results = []
    for host in subs:
        target = f"http://{host}"
        cmd = [
            TOOLS["nikto"],
            "-h", target,
            "-Format", "json",
            "-output", "-",
        ]
        log(f"Running nikto against {target}")
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                log(f"Nikto failed for {host}: {proc.stderr[:300]}")
                continue
            # Nikto sometimes outputs multiple JSON objects; attempt to parse leniently
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    results.append(obj)
                except Exception:
                    continue
        except FileNotFoundError:
            log("Nikto binary not found during run.")
            break
        except Exception as e:
            log(f"Nikto error for {host}: {e}")
            continue

    try:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    except Exception as e:
        log(f"Error writing Nikto JSON: {e}")
        return None

    return out_json if out_json.exists() else None


# ================== STATE ENRICHMENT ==================

def ensure_target_state(state: Dict[str, Any], domain: str) -> Dict[str, Any]:
    targets = state.setdefault("targets", {})
    tgt = targets.setdefault(domain, {
        "subdomains": {},
        "flags": {
            "amass_done": False,
            "ffuf_done": False,
            "httpx_done": False,
            "nuclei_done": False,
            "nikto_done": False,
        }
    })
    # Normalize missing keys
    tgt.setdefault("subdomains", {})
    tgt.setdefault("flags", {})
    for k in ["amass_done", "ffuf_done", "httpx_done", "nuclei_done", "nikto_done"]:
        tgt["flags"].setdefault(k, False)
    return tgt


def add_subdomains_to_state(state: Dict[str, Any], domain: str, subs: List[str], source: str) -> None:
    tgt = ensure_target_state(state, domain)
    submap = tgt["subdomains"]
    for s in subs:
        s = s.strip().lower()
        if not s:
            continue
        entry = submap.setdefault(s, {
            "sources": [],
            "httpx": None,
            "nuclei": [],
            "nikto": [],
        })
        if "sources" not in entry:
            entry["sources"] = []
        if source not in entry["sources"]:
            entry["sources"].append(source)


def enrich_state_with_httpx(state: Dict[str, Any], domain: str, httpx_json: Path) -> None:
    if not httpx_json or not httpx_json.exists():
        return
    tgt = ensure_target_state(state, domain)
    submap = tgt["subdomains"]
    try:
        with open(httpx_json, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                host = obj.get("host") or obj.get("url")
                if not host:
                    continue
                host = host.replace("https://", "").replace("http://", "").split("/")[0].lower()
                entry = submap.setdefault(host, {
                    "sources": [],
                    "httpx": None,
                    "nuclei": [],
                    "nikto": [],
                })
                entry["httpx"] = {
                    "url": obj.get("url"),
                    "status_code": obj.get("status_code"),
                    "content_length": obj.get("content_length"),
                    "title": obj.get("title"),
                    "webserver": obj.get("webserver"),
                    "tech": obj.get("tech"),
                }
    except Exception as e:
        log(f"Error enriching state with httpx data: {e}")


def enrich_state_with_nuclei(state: Dict[str, Any], domain: str, nuclei_json: Path) -> None:
    if not nuclei_json or not nuclei_json.exists():
        return
    tgt = ensure_target_state(state, domain)
    submap = tgt["subdomains"]
    try:
        with open(nuclei_json, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                host = obj.get("host") or obj.get("matched-at") or obj.get("url")
                if not host:
                    continue
                host = host.replace("https://", "").replace("http://", "").split("/")[0].lower()
                entry = submap.setdefault(host, {
                    "sources": [],
                    "httpx": None,
                    "nuclei": [],
                    "nikto": [],
                })
                finding = {
                    "template_id": obj.get("template-id"),
                    "name": (obj.get("info") or {}).get("name"),
                    "severity": (obj.get("info") or {}).get("severity"),
                    "matched_at": obj.get("matched-at") or obj.get("url"),
                }
                entry.setdefault("nuclei", []).append(finding)
    except Exception as e:
        log(f"Error enriching state with nuclei data: {e}")


def enrich_state_with_nikto(state: Dict[str, Any], domain: str, nikto_json: Path) -> None:
    if not nikto_json or not nikto_json.exists():
        return
    tgt = ensure_target_state(state, domain)
    submap = tgt["subdomains"]
    try:
        data = json.loads(nikto_json.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = [data]
        for obj in data:
            host = obj.get("host") or obj.get("target") or obj.get("banner")
            if not host:
                continue
            host = str(host).replace("https://", "").replace("http://", "").split("/")[0].lower()
            entry = submap.setdefault(host, {
                "sources": [],
                "httpx": None,
                "nuclei": [],
                "nikto": [],
            })
            vulns = obj.get("vulnerabilities") or obj.get("vulns") or []
            normalized_vulns = []
            for v in vulns:
                if isinstance(v, dict):
                    normalized_vulns.append({
                        "id": v.get("id"),
                        "msg": v.get("msg") or v.get("description"),
                        "osvdb": v.get("osvdb"),
                        "risk": v.get("risk"),
                        "uri": v.get("uri"),
                    })
                else:
                    normalized_vulns.append({"raw": str(v)})
            entry.setdefault("nikto", []).extend(normalized_vulns)
    except Exception as e:
        log(f"Error enriching state with nikto data: {e}")


# ================== DASHBOARD GENERATION ==================

def generate_html_dashboard() -> None:
    """
    Generate a single HTML file from the global state.
    All runs of this script share this dashboard.
    """
    state = load_state()
    targets = state.get("targets", {})

    # Very simple HTML; auto-refresh via meta
    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset='utf-8'>",
        f"<meta http-equiv='refresh' content='{HTML_REFRESH_SECONDS}'>",
        "<title>Recon Dashboard</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; background:#0f172a; color:#e5e7eb; padding: 20px; }",
        "h1 { color:#facc15; }",
        "h2 { color:#93c5fd; }",
        "table { border-collapse: collapse; width: 100%; margin-bottom: 30px; }",
        "th, td { border: 1px solid #1f2937; padding: 4px 6px; font-size: 12px; }",
        "th { background:#111827; }",
        "tr:nth-child(even) { background:#020617; }",
        ".tag { display:inline-block; padding:2px 6px; border-radius:999px; margin-right:4px; font-size:10px; }",
        ".sev-low { background:#0f766e; }",
        ".sev-medium { background:#eab308; }",
        ".sev-high { background:#f97316; }",
        ".sev-critical { background:#b91c1c; }",
        ".badge { background:#1f2937; padding:2px 6px; border-radius:999px; font-size:11px; margin-right:4px; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Recon Dashboard</h1>",
        f"<p>Last updated: {state.get('last_updated', 'never')}</p>",
    ]

    for domain, tgt in sorted(targets.items(), key=lambda x: x[0]):
        subs = tgt.get("subdomains", {})
        flags = tgt.get("flags", {})
        html_parts.append(f"<h2>{domain}</h2>")
        html_parts.append(
            "<p>"
            f"<span class='badge'>Subdomains: {len(subs)}</span>"
            f"<span class='badge'>Amass: {'✅' if flags.get('amass_done') else '⏳'}</span>"
            f"<span class='badge'>ffuf: {'✅' if flags.get('ffuf_done') else '⏳'}</span>"
            f"<span class='badge'>httpx: {'✅' if flags.get('httpx_done') else '⏳'}</span>"
            f"<span class='badge'>nuclei: {'✅' if flags.get('nuclei_done') else '⏳'}</span>"
            f"<span class='badge'>nikto: {'✅' if flags.get('nikto_done') else '⏳'}</span>"
            "</p>"
        )

        html_parts.append("<table>")
        html_parts.append(
            "<tr>"
            "<th>#</th>"
            "<th>Subdomain</th>"
            "<th>Sources</th>"
            "<th>HTTP</th>"
            "<th>Nuclei Findings</th>"
            "<th>Nikto Findings</th>"
            "</tr>"
        )
        for idx, (sub, info) in enumerate(sorted(subs.items(), key=lambda x: x[0]), start=1):
            sources = info.get("sources", [])
            httpx = info.get("httpx") or {}
            nuclei = info.get("nuclei") or []
            nikto = info.get("nikto") or []

            # HTTP summary
            http_summary = ""
            if httpx:
                http_summary = (
                    f"{httpx.get('status_code')} "
                    f"{httpx.get('title') or ''} "
                    f"[{httpx.get('webserver') or ''}]"
                )

            # Nuclei summary
            nuclei_bits = []
            for n in nuclei:
                sev = (n.get("severity") or "info").lower()
                cls = "sev-" + ("critical" if sev == "critical"
                                else "high" if sev == "high"
                                else "medium" if sev == "medium"
                                else "low")
                nuclei_bits.append(
                    f"<span class='tag {cls}'>{sev}: {n.get('template_id')}</span>"
                )
            nuclei_html = " ".join(nuclei_bits)

            # Nikto summary
            nikto_html = ""
            if nikto:
                nikto_html = f"{len(nikto)} findings"

            html_parts.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td>{sub}</td>"
                f"<td>{', '.join(sources)}</td>"
                f"<td>{http_summary}</td>"
                f"<td>{nuclei_html}</td>"
                f"<td>{nikto_html}</td>"
                "</tr>"
            )

        html_parts.append("</table>")

    html_parts.append("</body></html>")

    acquire_lock()
    try:
        tmp = HTML_DASHBOARD_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))
        tmp.replace(HTML_DASHBOARD_FILE)
    finally:
        release_lock()


def dashboard_loop(interval: int) -> None:
    """
    Background thread that keeps regenerating the HTML dashboard.
    All concurrent script runs will do this; they all share the same state.json and dashboard.html.
    """
    global HTML_REFRESH_SECONDS
    HTML_REFRESH_SECONDS = interval

    log(f"Dashboard loop started; HTML will be updated every {interval} seconds.")
    while True:
        try:
            generate_html_dashboard()
        except Exception as e:
            log(f"Error generating dashboard: {e}")
        time.sleep(interval)


# ================== MAIN PIPELINE ==================

def run_pipeline(domain: str, wordlist: str, skip_nikto: bool = False) -> None:
    ensure_dirs()

    # Start dashboard thread (daemon)
    t = threading.Thread(target=dashboard_loop, args=(HTML_REFRESH_SECONDS,), daemon=True)
    t.start()

    # Load state
    state = load_state()
    tgt = ensure_target_state(state, domain)
    flags = tgt["flags"]

    # ---------- Amass ----------
    if not flags.get("amass_done"):
        log(f"=== Amass enumeration for {domain} ===")
        amass_json = amass_enum(domain)
        if amass_json:
            subs = parse_amass_json(amass_json)
            log(f"Amass found {len(subs)} subdomains.")
            add_subdomains_to_state(state, domain, subs, "amass")
            flags["amass_done"] = True
            save_state(state)
        else:
            log("Amass enumeration skipped/failed; continuing.")

    # ---------- ffuf ----------
    if not flags.get("ffuf_done"):
        if not wordlist or not Path(wordlist).exists():
            log("ffuf wordlist not provided or not found; skipping ffuf brute-force.")
        else:
            log(f"=== ffuf brute-force for {domain} using {wordlist} ===")
            subs_ffuf = ffuf_bruteforce(domain, wordlist)
            log(f"ffuf found {len(subs_ffuf)} vhost subdomains.")
            add_subdomains_to_state(state, domain, subs_ffuf, "ffuf")
            flags["ffuf_done"] = True
            save_state(state)

    # Dedup & write subdomains file
    all_subs = sorted(ensure_target_state(state, domain)["subdomains"].keys())
    log(f"Total unique subdomains for {domain}: {len(all_subs)}")
    subs_file = write_subdomains_file(domain, all_subs)

    # ---------- httpx ----------
    if not flags.get("httpx_done"):
        log(f"=== httpx scan for {domain} ({len(all_subs)} hosts) ===")
        httpx_json = httpx_scan(subs_file, domain)
        enrich_state_with_httpx(state, domain, httpx_json)
        flags["httpx_done"] = True
        save_state(state)

    # ---------- nuclei ----------
    if not flags.get("nuclei_done"):
        log(f"=== nuclei scan for {domain} ({len(all_subs)} hosts) ===")
        nuclei_json = nuclei_scan(subs_file, domain)
        enrich_state_with_nuclei(state, domain, nuclei_json)
        flags["nuclei_done"] = True
        save_state(state)

    # ---------- nikto ----------
    if not skip_nikto and not flags.get("nikto_done"):
        log(f"=== nikto scan for {domain} ({len(all_subs)} hosts) ===")
        nikto_json = nikto_scan(all_subs, domain)
        enrich_state_with_nikto(state, domain, nikto_json)
        flags["nikto_done"] = True
        save_state(state)
    elif skip_nikto:
        log("Skipping nikto because --skip-nikto was set.")

    log("Pipeline finished for this run. Dashboard will keep refreshing while the script is running.")
    # Sleep a bit so dashboard thread has time to write at least once
    time.sleep(5)


# ================== CLI ==================

def main():
    parser = argparse.ArgumentParser(description="Recon pipeline + HTML dashboard")
    parser.add_argument("domain", help="Target domain / TLD (e.g. example.com)")
    parser.add_argument(
        "-w", "--wordlist",
        help="Wordlist path for ffuf subdomain brute-force (optional but recommended)."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Dashboard refresh interval in seconds (default: 30)."
    )
    parser.add_argument(
        "--skip-nikto",
        action="store_true",
        help="Skip Nikto scanning (can be heavy)."
    )

    args = parser.parse_args()

    global HTML_REFRESH_SECONDS
    HTML_REFRESH_SECONDS = max(5, args.interval)

    try:
        run_pipeline(args.domain, args.wordlist, skip_nikto=args.skip_nikto)
    except KeyboardInterrupt:
        log("Interrupted by user.")
    except Exception as e:
        log(f"Fatal error: {e}")


if __name__ == "__main__":
    main()
