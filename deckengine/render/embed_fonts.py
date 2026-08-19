"""Embed the deck's fonts into the .pptx — the definitive substitution fix.

The evaluated deck's view-time carnage happened because the file NAMES
Georgia/Segoe UI while the viewer's machine may not have them: PowerPoint
substitutes a non-metric face and re-wraps every line. Embedding the actual
font data means a viewer without our fonts never substitutes.

Pure-OOXML implementation (no COM, no soffice): PresentationML stores
embedded fonts as raw TTF parts (ppt/fonts/*.fntdata) referenced from
<p:embeddedFontLst> in presentation.xml. We embed, for every _KNOWN family
the deck references, whatever file the FontRegistry resolves — the real
Microsoft face on Windows, the metric clone on Linux (clones are SIL-OFL:
embedding is explicitly permitted).

Fonts whose OS/2 fsType forbids embedding (restricted license bit 0x2) are
skipped with a warning. ON by default; DECKENGINE_EMBED_FONTS=0 opts out
for trusted-viewer environments where smaller files matter more.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fontTools.ttLib import TTFont
from lxml import etree

from ..core.fonts import FontRegistry, default_registry

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_FONT_REL = _R + "/font"
_FNTDATA_CT = "application/x-fontdata"
_RESTRICTED = 0x0002  # OS/2 fsType: no embedding allowed

# p:presentation child order (ECMA-376 CT_Presentation) — embeddedFontLst
# must land after these, before custShowLst and the rest
_BEFORE_EMBED = {"sldMasterIdLst", "notesMasterIdLst", "handoutMasterIdLst",
                 "sldIdLst", "sldSz", "notesSz", "smartTags"}


def _fs_type(path: Path) -> int:
    tt = TTFont(str(path), lazy=True)
    try:
        return int(tt["OS/2"].fsType)
    finally:
        tt.close()


def _deck_families(zf: zipfile.ZipFile) -> set[str]:
    """Every typeface name referenced anywhere in the deck's XML."""
    fams: set[str] = set()
    for name in zf.namelist():
        if not name.endswith(".xml") or not name.startswith("ppt/"):
            continue
        root = etree.fromstring(zf.read(name))
        for el in root.iter():
            tf = el.get("typeface")
            if tf:
                fams.add(tf)
    return fams


def embed_fonts(pptx_path: Path, registry: FontRegistry | None = None,
                warn=None) -> int:
    """Embed resolved fonts for every referenced family; returns the number
    of font files embedded (0 = nothing to do / all skipped)."""
    reg = registry or default_registry()
    warn = warn or (lambda m: None)
    pptx_path = Path(pptx_path)

    with zipfile.ZipFile(pptx_path) as zf:
        fams = _deck_families(zf)

    # (family, bold, italic) -> file, deduped by file path (Selawik reuses
    # the upright file for italic; embed each file once per family)
    jobs: list[tuple[str, dict[str, Path]]] = []
    for fam in sorted(fams):
        slots: dict[str, Path] = {}
        for slot, bold, italic in (("regular", False, False),
                                   ("bold", True, False),
                                   ("italic", False, True),
                                   ("boldItalic", True, True)):
            try:
                p = reg.resolve(fam, bold=bold, italic=italic)
            except FileNotFoundError:
                continue
            if p.suffix.lower() not in (".ttf", ".otf"):
                continue
            if _fs_type(p) & _RESTRICTED:
                warn(f"embed_fonts: {p.name} forbids embedding (fsType); "
                     f"skipped for {fam!r}")
                continue
            if p in slots.values():
                continue  # same file standing in for two slots
            slots[slot] = p
        if slots:
            jobs.append((fam, slots))
    if not jobs:
        return 0

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".pptx",
                                        dir=str(pptx_path.parent))
    os.close(tmp_fd)  # ZipFile("w") truncates and rewrites it

    n_embedded = 0
    with zipfile.ZipFile(pptx_path) as zin, \
            zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED) as zout:
        pres_xml = etree.fromstring(zin.read("ppt/presentation.xml"))
        rels_xml = etree.fromstring(
            zin.read("ppt/_rels/presentation.xml.rels"))
        ct_xml = etree.fromstring(zin.read("[Content_Types].xml"))

        # next free rId in the presentation rels
        used = {r.get("Id") for r in rels_xml}
        next_id = 1
        font_parts: list[tuple[str, bytes]] = []
        embed_lst = etree.SubElement(pres_xml, f"{{{_P}}}embeddedFontLst")
        for fam, slots in jobs:
            ef = etree.SubElement(embed_lst, f"{{{_P}}}embeddedFont")
            fe = etree.SubElement(ef, f"{{{_P}}}font")
            fe.set("typeface", fam)
            for slot in ("regular", "bold", "italic", "boldItalic"):
                p = slots.get(slot)
                if p is None:
                    continue
                while f"rId{next_id}" in used:
                    next_id += 1
                rid = f"rId{next_id}"
                used.add(rid)
                part = f"fonts/font{len(font_parts) + 1}.fntdata"
                font_parts.append((f"ppt/{part}", p.read_bytes()))
                rel = etree.SubElement(rels_xml, f"{{{_REL}}}Relationship")
                rel.set("Id", rid)
                rel.set("Type", _FONT_REL)
                rel.set("Target", part)
                se = etree.SubElement(ef, f"{{{_P}}}{slot}")
                se.set(f"{{{_R}}}id", rid)
                n_embedded += 1

        # move embeddedFontLst into schema position
        idx = 0
        for i, child in enumerate(list(pres_xml)):
            if etree.QName(child).localname in _BEFORE_EMBED:
                idx = i + 1
        pres_xml.remove(embed_lst)
        pres_xml.insert(idx, embed_lst)
        pres_xml.set("embedTrueTypeFonts", "1")

        # content type for .fntdata
        if not any(d.get("Extension") == "fntdata"
                   for d in ct_xml.findall(f"{{{_CT}}}Default")):
            d = etree.SubElement(ct_xml, f"{{{_CT}}}Default")
            d.set("Extension", "fntdata")
            d.set("ContentType", _FNTDATA_CT)
            # Defaults must precede Overrides
            ct_xml.remove(d)
            ct_xml.insert(0, d)

        replaced = {"ppt/presentation.xml": etree.tostring(
                        pres_xml, xml_declaration=True, encoding="UTF-8",
                        standalone=True),
                    "ppt/_rels/presentation.xml.rels": etree.tostring(
                        rels_xml, xml_declaration=True, encoding="UTF-8",
                        standalone=True),
                    "[Content_Types].xml": etree.tostring(
                        ct_xml, xml_declaration=True, encoding="UTF-8",
                        standalone=True)}
        for info in zin.infolist():
            data = replaced.get(info.filename) or zin.read(info.filename)
            zout.writestr(info, data)
        for name, data in font_parts:
            zout.writestr(name, data)

    shutil.move(tmp_name, pptx_path)
    return n_embedded
