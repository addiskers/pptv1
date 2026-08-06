"""Raw OOXML helpers for effects python-pptx doesn't expose cleanly.

Everything here is deliberately isolated and commented — the rest of the engine
uses python-pptx's API. Only reach for these when there is no API path.
"""
from __future__ import annotations

from pptx.oxml.ns import qn


def set_series_line_dash(series, dash: str = "dash") -> None:
    """Dash a line-chart series (the forecast half).

    python-pptx exposes series.format.line but not a dash preset on chart
    series lines reliably across versions, so we write <a:prstDash> into the
    series spPr/ln directly (creating the ln if the series has no explicit
    line yet).
    """
    ser = series._element
    spPr = ser.find(qn("c:spPr"))
    if spPr is None:
        spPr = ser.makeelement(qn("c:spPr"), {})
        # spPr goes after c:tx/c:order/c:idx — appending is schema-tolerant
        # for the reader; PowerPoint re-orders on save.
        ser.append(spPr)
    ln = spPr.find(qn("a:ln"))
    if ln is None:
        ln = spPr.makeelement(qn("a:ln"), {})
        spPr.append(ln)
    for old in ln.findall(qn("a:prstDash")):
        ln.remove(old)
    ln.append(ln.makeelement(qn("a:prstDash"), {"val": dash}))


def add_point_data_labels(series, indices, number_format: str,
                          font_pt: float, color_hex: str) -> None:
    """Show value labels on ONLY the given point indices of a series.

    Used for endpoint labels (first + last point of a line). python-pptx has
    no per-point dLbl API, so we build <c:dLbls> with one <c:dLbl> per index
    (showVal=1, everything else off) plus a group-level "delete all" default
    so the other points stay unlabeled.
    """
    ser = series._element
    for old in ser.findall(qn("c:dLbls")):
        ser.remove(old)
    dLbls = ser.makeelement(qn("c:dLbls"), {})
    for idx in indices:
        dLbl = dLbls.makeelement(qn("c:dLbl"), {})
        dLbl.append(dLbl.makeelement(qn("c:idx"), {"val": str(idx)}))
        _txpr(dLbl, font_pt, color_hex)
        dLbl.append(_numfmt(number_format))
        _show_val_only(dLbl)
        dLbls.append(dLbl)
    # group default: label nothing (the per-idx dLbls above win)
    dLbls.append(_numfmt(number_format))
    _show_val_only(dLbls, show=False)
    # c:dLbls must precede c:cat/c:val in the series; insert before c:cat
    cat = ser.find(qn("c:cat"))
    if cat is not None:
        cat.addprevious(dLbls)
    else:
        ser.append(dLbls)


def _numfmt(fmt: str):
    from lxml import etree
    el = etree.SubElement(etree.Element(qn("c:_tmp")), qn("c:numFmt"))
    el.set("formatCode", fmt)
    el.set("sourceLinked", "0")
    return el


def _show_val_only(parent, show: bool = True) -> None:
    for tag, val in (("c:showLegendKey", "0"), ("c:showVal", "1" if show else "0"),
                     ("c:showCatName", "0"), ("c:showSerName", "0"),
                     ("c:showPercent", "0"), ("c:showBubbleSize", "0")):
        parent.append(parent.makeelement(qn(tag), {"val": val}))


def _txpr(dLbl, font_pt: float, color_hex: str) -> None:
    """Minimal <c:txPr> so per-point labels honor size + color."""
    txPr = dLbl.makeelement(qn("c:txPr"), {})
    body = txPr.makeelement(qn("a:bodyPr"), {})
    lst = txPr.makeelement(qn("a:lstStyle"), {})
    p = txPr.makeelement(qn("a:p"), {})
    pPr = p.makeelement(qn("a:pPr"), {})
    defRPr = pPr.makeelement(qn("a:defRPr"),
                             {"sz": str(int(font_pt * 100)), "b": "1"})
    fill = defRPr.makeelement(qn("a:solidFill"), {})
    fill.append(fill.makeelement(qn("a:srgbClr"), {"val": color_hex}))
    defRPr.append(fill)
    pPr.append(defRPr)
    p.append(pPr)
    txPr.append(body)
    txPr.append(lst)
    txPr.append(p)
    dLbl.append(txPr)


def add_soft_shadow(shape, *, blur_emu: int = 40000, dist_emu: int = 24000,
                    direction: int = 5400000, alpha_pct: int = 62,
                    color: str = "1A1A1A") -> None:
    """Attach a subtle outer drop-shadow to an autoshape.

    Gives white content-cards the 'floating on canvas' depth of hand-built
    consulting decks. python-pptx has no shadow-build API (only shadow.inherit),
    so we insert <a:effectLst><a:outerShdw> into spPr directly.

    direction: 5400000 = 90° (down-right). alpha_pct: shadow opacity.
    """
    spPr = shape._element.spPr
    for old in spPr.findall(qn("a:effectLst")):
        spPr.remove(old)
    eff = spPr.makeelement(qn("a:effectLst"), {})
    shdw = eff.makeelement(qn("a:outerShdw"), {
        "blurRad": str(blur_emu), "dist": str(dist_emu),
        "dir": str(direction), "rotWithShape": "0"})
    clr = shdw.makeelement(qn("a:srgbClr"), {"val": color})
    alpha = clr.makeelement(qn("a:alpha"), {"val": str(alpha_pct * 1000)})
    clr.append(alpha)
    shdw.append(clr)
    eff.append(shdw)
    # effectLst must follow the fill/line group in spPr; append is schema-valid
    # because those precede it, and ln (if present) is already before this point
    spPr.append(eff)
