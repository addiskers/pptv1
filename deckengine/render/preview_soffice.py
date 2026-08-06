"""LibreOffice preview renderer (Linux / server path).

pptx -> pdf via headless soffice with a PER-JOB isolated user profile, then
rasterize each PDF page with pypdfium2. Matches export_pngs_powerpoint's
contract exactly (writes slideNN.png, returns the sorted list) so the API
preview endpoint and the vision judge need no changes — only the provider seam
(preview_provider.get_preview_exporter) chooses this over COM.

Notes learned from the design review:
- `soffice --convert-to png` only exports slide 1; go through PDF.
- soffice fails hard if a second instance shares the default profile, so each
  job gets a throwaway `-env:UserInstallation` profile dir.
- A stale profile lock is the dominant transient failure — on timeout/failure
  we kill the tree and retry ONCE with a fresh profile.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_TIMEOUT = 150


def _soffice_bin() -> str:
    return os.environ.get("DECKENGINE_SOFFICE", "soffice")


def _convert_to_pdf(pptx: Path, out_dir: Path) -> Path:
    """One soffice run in an isolated profile; returns the produced PDF."""
    profile = Path(tempfile.mkdtemp(prefix="deckengine_lo_"))
    try:
        # file:// URL form is required by -env:UserInstallation
        prof_url = "file://" + str(profile).replace("\\", "/")
        proc = subprocess.run(
            [_soffice_bin(), "--headless", "--invisible", "--nologo",
             "--nodefault", "--nolockcheck", "--norestore",
             f"-env:UserInstallation={prof_url}",
             "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx)],
            capture_output=True, text=True, timeout=_TIMEOUT)
        pdf = out_dir / (pptx.stem + ".pdf")
        if proc.returncode != 0 or not pdf.is_file():
            raise RuntimeError(
                f"soffice pptx->pdf failed: {proc.stdout}\n{proc.stderr}")
        return pdf
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def export_pngs_soffice(pptx_path: str | Path, out_dir: str | Path,
                        width: int = 1280, height: int = 720) -> list[Path]:
    """Render every slide to PNG via soffice->pdf->pypdfium2. One fresh-profile
    retry absorbs the common stale-lock failure."""
    import pypdfium2 as pdfium

    pptx_path = Path(pptx_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deckengine_pdf_") as tmp:
        tmp_dir = Path(tmp)
        try:
            pdf_path = _convert_to_pdf(pptx_path, tmp_dir)
        except (subprocess.TimeoutExpired, RuntimeError):
            pdf_path = _convert_to_pdf(pptx_path, tmp_dir)  # one retry

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            out: list[Path] = []
            for i in range(len(pdf)):
                page = pdf[i]
                pw = page.get_size()[0]  # points
                scale = (width / pw) if pw else 2.0
                bitmap = page.render(scale=scale)
                img = bitmap.to_pil()
                dest = out_dir / f"slide{i + 1:02d}.png"
                img.save(dest)
                out.append(dest)
            return sorted(out)
        finally:
            pdf.close()
