"""onvif-scan command-line interface."""
from __future__ import annotations

import datetime as _dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from . import store, discovery, onvif_client, capture, reporting
from .config import DEFAULT_EMAIL_TO
from .creds import CredentialStore
from .models import ScanResult, Device

app = typer.Typer(add_completion=False, help="Discover, test and report on ONVIF cameras.")
console = Console()


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------------- doctor
@app.command()
def doctor():
    """Check the environment (ffmpeg, discovery deps)."""
    console.print(f"[bold]onvif-scan[/] v{__version__}")
    ok = True
    if capture.ffmpeg_available():
        console.print("  [green]✓[/] ffmpeg / ffprobe found")
    else:
        ok = False
        console.print("  [red]✗[/] ffmpeg not found — install: "
                      "brew install ffmpeg | apt install ffmpeg")
    for mod, label in [("wsdiscovery", "WS-Discovery"), ("onvif", "onvif-zeep"),
                       ("cv2", "OpenCV"), ("openpyxl", "openpyxl")]:
        try:
            __import__(mod)
            console.print(f"  [green]✓[/] {label}")
        except Exception as e:
            ok = False
            console.print(f"  [red]✗[/] {label}: {e}")
    subs = discovery.auto_subnets()
    console.print(f"  detected subnet(s): {', '.join(subs) or '(none)'}")
    raise typer.Exit(0 if ok else 1)


# --------------------------------------------------------------------------- search
@app.command()
def search(
    subnet: List[str] = typer.Option(None, "--subnet", help="CIDR(s) to probe. Auto-detect if omitted."),
    method: str = typer.Option("ws,probe", help="ws,probe (comma-separated)."),
    timeout: int = typer.Option(5, help="WS-Discovery wait seconds."),
    workdir: Optional[str] = typer.Option(None, "--workdir", help="Working directory."),
    client: str = typer.Option("", help="Client name to stamp on the report."),
):
    """Discover ONVIF devices and save the list."""
    wd = store.workdir(workdir)
    methods = [m.strip() for m in method.split(",") if m.strip()]
    found: List[List[Device]] = []

    if "ws" in methods:
        console.print("[bold]WS-Discovery[/] (multicast)…")
        ws = discovery.ws_discover(timeout=timeout)
        console.print(f"  found {len(ws)} via multicast")
        found.append(ws)

    if "probe" in methods:
        subs = subnet or discovery.auto_subnets()
        console.print(f"[bold]Active probe[/] of {', '.join(subs) or '(none)'}…")
        pr = discovery.probe_subnets(subs)
        console.print(f"  found {len(pr)} hosts with camera ports open")
        found.append(pr)

    devices = discovery.merge_devices(*found)
    result = ScanResult(client=client, scanned_at=_now(), devices=devices)
    out = store.save(result, wd)

    table = Table(title=f"{len(devices)} device(s)")
    for col in ("IP", "ONVIF URL", "Open ports"):
        table.add_column(col)
    for d in devices:
        table.add_row(d.ip, d.onvif_url or "[dim]-[/]", ",".join(map(str, d.open_ports)) or "-")
    console.print(table)
    console.print(f"saved → {out}")
    console.print(f"edit [cyan]{wd/'devices.txt'}[/] to trim the list before `onvif-scan test`")


# --------------------------------------------------------------------------- test
def _test_device(dev: Device, creds: CredentialStore, wd: Path,
                 frames: int, shots: int, timeout: int) -> Device:
    auth_ok = False
    last_err = None
    for (user, pw) in creds.candidates():
        ok, streams, err = onvif_client.enumerate_streams(dev, user, pw, timeout=timeout)
        if ok:
            auth_ok = True
            creds.remember(user, pw)
            dev.streams = streams
            dev.auth = "ok"
            dev.error = None
            break
        last_err = err
        if err != "auth failed":
            break  # not an auth problem; don't keep trying creds

    if not auth_ok:
        prompted = creds.prompt(dev.ip)
        if prompted:
            ok, streams, err = onvif_client.enumerate_streams(dev, *prompted, timeout=timeout)
            if ok:
                auth_ok = True
                creds.remember(*prompted)
                dev.streams = streams
                dev.auth = "ok"
                dev.error = None
            else:
                last_err = err

    if not auth_ok:
        dev.auth = "failed" if last_err == "auth failed" else dev.auth
        dev.error = last_err or "could not enumerate streams"
        return dev

    shots_dir = wd / "shots"
    for s in dev.streams:
        capture.capture_and_measure(s, shots_dir, dev.ip, frames=frames, shots=shots, timeout=timeout)
    return dev


@app.command()
def test(
    workdir: Optional[str] = typer.Option(None, "--workdir"),
    frames: int = typer.Option(100, help="Frames to sample per stream for FPS."),
    shots: int = typer.Option(2, help="Screenshots per stream."),
    user: str = typer.Option("", "--user", help="Try this username first."),
    password: str = typer.Option("", "--pass", help="Try this password first."),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Never prompt for creds."),
    try_defaults: bool = typer.Option(False, "--try-defaults",
                                      help="Also try common vendor-default credentials (may trip lockouts)."),
    timeout: int = typer.Option(20, help="Per-stream timeout seconds."),
    workers: int = typer.Option(4, help="Parallel cameras."),
):
    """Connect to each device, enumerate streams, capture & grade."""
    wd = store.workdir(workdir)
    result = store.load(wd)
    if not capture.ffmpeg_available():
        console.print("[red]ffmpeg not found[/] — run `onvif-scan doctor`")
        raise typer.Exit(1)

    creds = CredentialStore(user, password, no_prompt=no_prompt, try_defaults=try_defaults)
    console.print(f"Testing {len(result.devices)} device(s)…")

    # NOTE: prompting is interactive, so we test serially when prompts are possible.
    if no_prompt and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_test_device, d, creds, wd, frames, shots, timeout): d
                    for d in result.devices}
            done = []
            for fut in as_completed(futs):
                done.append(fut.result())
    else:
        for d in result.devices:
            console.print(f"  [bold]{d.ip}[/] {d.model or ''}…")
            _test_device(d, creds, wd, frames, shots, timeout)

    store.save(result, wd)

    table = Table(title="Test results")
    for col in ("IP", "Streams", "Best res", "Best FPS", "Status"):
        table.add_column(col)
    for d in result.devices:
        ok = [s for s in d.streams if s.error is None]
        best = max((s for s in ok), key=lambda s: s.width * s.height, default=None)
        bestfps = max((s.fps_measured for s in ok), default=0)
        color = {"good": "green", "usable": "yellow", "failed": "red"}.get(d.status, "white")
        table.add_row(d.ip, str(len(d.streams)), best.resolution if best else "-",
                      str(bestfps), f"[{color}]{d.status}[/]")
    console.print(table)
    console.print("run [cyan]onvif-scan report[/] to build the deliverables")


# --------------------------------------------------------------------------- report
@app.command()
def report(
    workdir: Optional[str] = typer.Option(None, "--workdir"),
    fmt: str = typer.Option("xlsx,html", "--format", help="xlsx,html"),
    email: bool = typer.Option(False, "--email", help="Email via relay."),
    to: List[str] = typer.Option(None, "--to", help="Recipient(s)."),
    from_name: str = typer.Option("", "--from-name", help="Who ran the scan."),
):
    """Build Excel + HTML reports (and optionally email them)."""
    wd = store.workdir(workdir)
    result = store.load(wd)
    formats = [f.strip() for f in fmt.split(",")]
    xlsx_path = wd / "onboarding-report.xlsx"
    html_path = wd / "onboarding-report.html"

    if "xlsx" in formats:
        reporting.build_excel(result, wd, xlsx_path)
        console.print(f"  [green]✓[/] {xlsx_path}")
    if "html" in formats:
        reporting.build_html(result, wd, html_path)
        console.print(f"  [green]✓[/] {html_path}")

    if email:
        recipients = list(to) if to else DEFAULT_EMAIL_TO
        console.print(f"emailing report to {', '.join(recipients)}…")
        ok, msg = reporting.email_report(result, html_path, xlsx_path, recipients, from_name)
        console.print(f"  {'[green]sent[/]' if ok else '[red]failed[/]'}: {msg}")


# --------------------------------------------------------------------------- run
@app.command()
def run(
    subnet: List[str] = typer.Option(None, "--subnet"),
    workdir: Optional[str] = typer.Option(None, "--workdir"),
    client: str = typer.Option("", help="Client name."),
    frames: int = typer.Option(100),
    shots: int = typer.Option(2),
    user: str = typer.Option("", "--user"),
    password: str = typer.Option("", "--pass"),
    no_prompt: bool = typer.Option(False, "--no-prompt"),
    email: bool = typer.Option(False, "--email"),
    to: List[str] = typer.Option(None, "--to"),
):
    """search → test → report in one shot."""
    search(subnet=subnet, method="ws,probe", timeout=5, workdir=workdir, client=client)
    test(workdir=workdir, frames=frames, shots=shots, user=user, password=password,
         no_prompt=no_prompt, timeout=20, workers=4)
    report(workdir=workdir, fmt="xlsx,html", email=email, to=to, from_name="")


if __name__ == "__main__":
    app()
