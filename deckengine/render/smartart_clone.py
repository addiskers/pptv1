"""True SmartArt via template cloning — python-pptx cannot author dgm.

A SmartArt object is five parts: data / layout / quickStyle / colors +
a cached drawing. We reuse the LAYOUT + QUICKSTYLE + COLORS parts from
pre-authored templates (assets/smartart/*.pptx, made once in PowerPoint
by tools/make_smartart_templates.py), SYNTHESIZE the data model fresh
(doc point + node points + parOf connections with par/sib transition
points — the shape real PowerPoint files use), recolor the colorsDef's
accent1 references to the deck theme's primary, and OMIT the cached
drawing entirely: PowerPoint regenerates it on open. Consequence
(documented everywhere user-facing): LibreOffice/server previews show an
empty frame for the diagram until the file is opened in PowerPoint.
"""
from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

from lxml import etree
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.oxml import parse_xml

_REPO = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = _REPO / "assets" / "smartart"
TEMPLATES = ("org_chart", "issue_tree", "cycle", "radial")

_DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"

_CT = {
    "data": "application/vnd.openxmlformats-officedocument.drawingml"
            ".diagramData+xml",
    "layout": "application/vnd.openxmlformats-officedocument.drawingml"
              ".diagramLayout+xml",
    "quickStyle": "application/vnd.openxmlformats-officedocument"
                  ".drawingml.diagramStyle+xml",
    "colors": "application/vnd.openxmlformats-officedocument.drawingml"
              ".diagramColors+xml",
}
_RT = {
    "data": _R + "/diagramData",
    "layout": _R + "/diagramLayout",
    "quickStyle": _R + "/diagramQuickStyle",
    "colors": _R + "/diagramColors",
}


def _gid() -> str:
    return "{%s}" % str(uuid.uuid4()).upper()


def _load_template(name: str) -> dict:
    """{'layout': bytes, 'quickStyle': bytes, 'colors': bytes,
    'prset': dict of doc-pt prSet attrs from the template's data model}."""
    path = TEMPLATE_DIR / f"{name}.pptx"
    with zipfile.ZipFile(path) as zf:
        parts = {"layout": zf.read("ppt/diagrams/layout1.xml"),
                 "quickStyle": zf.read("ppt/diagrams/quickStyle1.xml"),
                 "colors": zf.read("ppt/diagrams/colors1.xml")}
        data = etree.fromstring(zf.read("ppt/diagrams/data1.xml"))
    doc_pt = next(p for p in data.iter(f"{{{_DGM}}}pt")
                  if p.get("type") == "doc")
    prset = doc_pt.find(f"{{{_DGM}}}prSet")
    parts["prset"] = dict(prset.attrib) if prset is not None else {}
    return parts


def _recolor(colors_blob: bytes, primary_hex: str) -> bytes:
    """Point the colorsDef's accent1 scheme references at the deck theme's
    primary so SmartArt matches the deck instead of Office blue. Children
    (tints/shades) are preserved — they modulate the new base color."""
    root = etree.fromstring(colors_blob)
    for el in root.iter(f"{{{_A}}}schemeClr"):
        if el.get("val") == "accent1":
            el.tag = f"{{{_A}}}srgbClr"
            el.set("val", primary_hex)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          standalone=True)


def _data_model(nodes: list[dict], prset: dict) -> bytes:
    """Fresh dgm data model: doc pt + node/parTrans/sibTrans points +
    parOf cxns — no presentation points (PowerPoint lays out on open).
    nodes: recursive [{'label': str, 'children': [...]}] — hierarchy depth
    is the caller's contract (org/issue nest under ONE root; cycle is
    flat; radial nests spokes under the center)."""
    nsmap = {"dgm": _DGM, "a": _A, "r": _R}
    root = etree.Element(f"{{{_DGM}}}dataModel", nsmap=nsmap)
    ptlst = etree.SubElement(root, f"{{{_DGM}}}ptLst")
    cxnlst = etree.SubElement(root, f"{{{_DGM}}}cxnLst")

    def add_pt(pid: str, ptype: str | None = None,
               text: str | None = None) -> None:
        pt = etree.SubElement(ptlst, f"{{{_DGM}}}pt", modelId=pid)
        if ptype:
            pt.set("type", ptype)
        if ptype == "doc" and prset:
            etree.SubElement(pt, f"{{{_DGM}}}prSet", **prset)
        else:
            etree.SubElement(pt, f"{{{_DGM}}}prSet")
        etree.SubElement(pt, f"{{{_DGM}}}spPr")
        t = etree.SubElement(pt, f"{{{_DGM}}}t")
        etree.SubElement(t, f"{{{_A}}}bodyPr")
        etree.SubElement(t, f"{{{_A}}}lstStyle")
        p = etree.SubElement(t, f"{{{_A}}}p")
        if text:
            r = etree.SubElement(p, f"{{{_A}}}r")
            rpr = etree.SubElement(r, f"{{{_A}}}rPr")
            rpr.set("lang", "en-US")
            at = etree.SubElement(r, f"{{{_A}}}t")
            at.text = text
        else:
            epr = etree.SubElement(p, f"{{{_A}}}endParaRPr")
            epr.set("lang", "en-US")

    def connect(parent: str, child: str, ord_: int) -> None:
        par_t, sib_t = _gid(), _gid()
        add_pt(par_t, "parTrans")
        add_pt(sib_t, "sibTrans")
        etree.SubElement(
            cxnlst, f"{{{_DGM}}}cxn", modelId=_gid(), srcId=parent,
            destId=child, srcOrd=str(ord_), destOrd="0",
            parTransId=par_t, sibTransId=sib_t)

    def add_subtree(parent: str, node: dict, ord_: int) -> None:
        nid = _gid()
        add_pt(nid, None, node["label"])
        connect(parent, nid, ord_)
        for j, child in enumerate(node.get("children") or []):
            add_subtree(nid, child, j)

    doc = _gid()
    add_pt(doc, "doc")
    for i, node in enumerate(nodes):
        add_subtree(doc, node, i)
    etree.SubElement(root, f"{{{_DGM}}}bg")
    etree.SubElement(root, f"{{{_DGM}}}whole")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          standalone=True)


def _free_index(package) -> int:
    used = {str(p.partname) for p in package.iter_parts()}
    i = 1
    while f"/ppt/diagrams/data{i}.xml" in used:
        i += 1
    return i


def add_smart_diagram(slide, layout_name: str, nodes: list[dict],
                      x: int, y: int, w: int, h: int,
                      primary_hex: str) -> None:
    """Insert a REAL SmartArt graphicFrame on the slide (raises on any
    problem — the component catches and falls back to a drawn form)."""
    tpl = _load_template(layout_name)
    package = slide.part.package
    idx = _free_index(package)

    blobs = {"data": _data_model(nodes, tpl["prset"]),
             "layout": tpl["layout"],
             "quickStyle": tpl["quickStyle"],
             "colors": _recolor(tpl["colors"], primary_hex)}
    names = {"data": f"/ppt/diagrams/data{idx}.xml",
             "layout": f"/ppt/diagrams/layout{idx}.xml",
             "quickStyle": f"/ppt/diagrams/quickStyle{idx}.xml",
             "colors": f"/ppt/diagrams/colors{idx}.xml"}
    rids = {}
    for key in ("data", "layout", "quickStyle", "colors"):
        part = Part(PackURI(names[key]), _CT[key], package, blobs[key])
        rids[key] = slide.part.relate_to(part, _RT[key])

    sp_tree = slide.shapes._spTree
    shape_id = max([int(el.get("id")) for el in
                    sp_tree.iter(f"{{{_P}}}cNvPr")] or [1]) + 1
    frame = parse_xml(
        f'<p:graphicFrame '
        f'xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}">'
        f'<p:nvGraphicFramePr>'
        f'<p:cNvPr id="{shape_id}" name="SmartDiagram {shape_id}"/>'
        f'<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
        f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/>'
        f'</p:xfrm>'
        f'<a:graphic><a:graphicData '
        f'uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
        f'<dgm:relIds xmlns:dgm="{_DGM}" '
        f'r:dm="{rids["data"]}" r:lo="{rids["layout"]}" '
        f'r:qs="{rids["quickStyle"]}" r:cs="{rids["colors"]}"/>'
        f'</a:graphicData></a:graphic></p:graphicFrame>')
    sp_tree.append(frame)
