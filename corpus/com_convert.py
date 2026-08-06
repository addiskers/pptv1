"""Windows PowerPoint COM helpers for corpus ingest.

Adapts the PowerShell-over-COM pattern from deckengine/render/preview.py:
one PowerPoint session per deck, driven by a short PowerShell script, so
no persistent COM state leaks between decks. On timeout the PowerShell
child is killed by subprocess and any orphaned POWERPNT.EXE is taskkilled.
When COM/Office is missing (non-Windows box, PowerPoint not installed)
functions raise ComUnavailable so ingest can log-and-skip the deck rather
than crash the walk. No win32com import is needed for this approach.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class ComUnavailable(RuntimeError):
    """PowerPoint COM automation is not available on this machine."""


_COM_MISSING_MARKERS = (
    "80040154",              # REGDB_E_CLASSNOTREG
    "class factory",
    "invalid class string",
    "not registered",
    "cannot create the object",
)

_EXPORT_PS = r"""
$ErrorActionPreference = 'Stop'
$pp = New-Object -ComObject PowerPoint.Application
try {{
  $pres = $pp.Presentations.Open('{pptx}', $true, $false, $false)
  $i = 1
  foreach ($s in $pres.Slides) {{
    $s.Export('{outdir}\slide{{0:d3}}.png' -f $i, 'PNG', {w}, {h})
    $i++
  }}
  $pres.Close()
  Write-Output "OK $($i - 1)"
}} finally {{
  $pp.Quit()
}}
"""

_CONVERT_PS = r"""
$ErrorActionPreference = 'Stop'
$pp = New-Object -ComObject PowerPoint.Application
try {{
  $pres = $pp.Presentations.Open('{src}', $true, $false, $false)
  $pres.SaveAs('{dst}', 24)
  $pres.Close()
  Write-Output "OK"
}} finally {{
  $pp.Quit()
}}
"""


def _ps_quote(path: Path) -> str:
    # single-quoted PS string: only ' needs escaping (doubled)
    return str(path).replace("'", "''")


def _run_ps(script: str, timeout: int) -> subprocess.CompletedProcess:
    if sys.platform != "win32":
        raise ComUnavailable("PowerPoint COM requires Windows")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             script],
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ComUnavailable("powershell.exe not found") from exc
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["taskkill", "/IM", "POWERPNT.EXE", "/F"],
                       capture_output=True)
        raise RuntimeError(
            f"PowerPoint COM timed out after {timeout}s") from exc
    if proc.returncode != 0 or "OK" not in proc.stdout:
        err = f"{proc.stdout}\n{proc.stderr}".strip()
        low = err.lower()
        if any(m in low for m in _COM_MISSING_MARKERS):
            raise ComUnavailable(f"PowerPoint COM unavailable: {err}")
        raise RuntimeError(
            f"PowerPoint COM failed (possible repair prompt): {err}")
    return proc


def ppt_to_pptx(src: str | Path, out_dir: str | Path,
                timeout: int = 180) -> Path:
    """Convert a legacy .ppt to .pptx via PowerPoint SaveAs (format 24)."""
    src = Path(src).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.stem + ".pptx")
    script = _CONVERT_PS.format(src=_ps_quote(src), dst=_ps_quote(dst))
    _run_ps(script, timeout=timeout)
    if not dst.exists():
        raise RuntimeError(f"SaveAs produced no file: {dst}")
    return dst


def export_slide_pngs(pptx: str | Path, out_dir: str | Path,
                      width: int = 1280, height: int = 720,
                      timeout: int = 300) -> list[Path]:
    """Export every slide of a pptx as PNG via one PowerPoint session."""
    pptx = Path(pptx).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # The return value below is glob-based, so stale PNGs from a previous
    # export of this deck (e.g. the deck shrank between runs) would be
    # returned as if PowerPoint had just written them. Clear them first.
    for old in out_dir.glob("slide*.png"):
        old.unlink()
    script = _EXPORT_PS.format(pptx=_ps_quote(pptx),
                               outdir=_ps_quote(out_dir),
                               w=width, h=height)
    _run_ps(script, timeout=timeout)
    return sorted(out_dir.glob("slide*.png"))
