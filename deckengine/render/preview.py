"""Preview + validation renderers.

On Windows dev boxes with Office installed, real PowerPoint (COM) is the golden
oracle: it both proves the file opens without a repair prompt and exports
ground-truth PNGs. (Server path — LibreOffice: pptx -> pdf via soffice with an
isolated profile, then rasterize with pypdfium2. soffice --convert-to png only
exports slide 1; do not use it.)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$pp = New-Object -ComObject PowerPoint.Application
try {{
  $pres = $pp.Presentations.Open('{pptx}', $true, $false, $false)
  $i = 1
  foreach ($s in $pres.Slides) {{
    $s.Export('{outdir}\slide{{0:d2}}.png' -f $i, 'PNG', {w}, {h})
    $i++
  }}
  $pres.Close()
  Write-Output "OK $($i - 1)"
}} finally {{
  $pp.Quit()
}}
"""


def export_pngs_powerpoint(pptx_path: str | Path, out_dir: str | Path,
                           width: int = 1920, height: int = 1080) -> list[Path]:
    """Open in real PowerPoint via COM and export every slide as PNG.

    Raises RuntimeError if PowerPoint cannot open the file cleanly — this is the
    'no repair prompt' acceptance gate.
    """
    pptx_path = Path(pptx_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    script = _PS_TEMPLATE.format(pptx=pptx_path, outdir=out_dir, w=width, h=height)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or "OK" not in proc.stdout:
        raise RuntimeError(
            f"PowerPoint COM export failed (possible repair prompt): "
            f"{proc.stdout}\n{proc.stderr}")
    return sorted(out_dir.glob("slide*.png"))
