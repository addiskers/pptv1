"""Layout-pattern clustering over the corpus index — pure python.

CLI:  python corpus/cluster.py [--work DIR] [--out FILE]
                               [--threshold FLOAT]

Joins work/index.jsonl (SlideRecord) with work/filtered.jsonl
(FilterVerdict {slide_id, keep, reasons}) and work/scores.jsonl
(DetScore {slide_id, score, parts}), builds a layout signature per
kept slide, and greedily clusters: slides are visited by det score
descending and join the first existing cluster whose centroid is
closer than the threshold, else seed a new one. Single pass, no
sklearn, fully deterministic.

Signature = 5-dim shape-type histogram (textboxes/pictures/tables/
charts/groups over n_shapes) + presence bits of x/y edges quantized
into 12 horizontal / 8 vertical bins + all 256 bits of the 16x16
dhash (corpus/ingest.py dhash()).
PDF records (shape_stats None) carry only the phash bits; distance
weights renormalize over the components BOTH sides have, so phash-only
records still separate (a fixed 0.2 weight could never cross the
0.35 threshold).

Design: signature/distance/greedy are pure functions over plain dicts
(reading raw dicts keeps this tolerant of ShapeStats schema growth);
only run_cluster touches the filesystem. clusters.jsonl is a
full-recompute snapshot and is OVERWRITTEN each run — appending would
duplicate cluster ids — unlike the append-only upstream artifacts.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

X_BINS = 12
Y_BINS = 8
# 16:9 default extent in points; 4:3 decks and overflowing shapes
# simply clamp into the last bin — bins are presence features, not
# measurements, so a coarse shared grid is fine.
SLIDE_W_PT = 960.0
SLIDE_H_PT = 540.0
# corpus/ingest.py dhash() emits a 256-bit (16x16) hash; use ALL of it.
# Truncating to the low 64 bits would keep only the bottom 4 image rows
# — the footer/page-number band — the worst possible subset for the
# PDF records whose ONLY signal is this hash.
PHASH_BITS = 256
W_HIST = 0.5
W_EDGE = 0.3
W_PHASH = 0.2
THRESHOLD = 0.35
MAX_EXEMPLARS = 3


class ClusterRecord(BaseModel):
    cluster_id: str
    slide_ids: list[str]
    exemplar_slide_ids: list[str]
    size: int


# --- signatures ---------------------------------------------------------------

@dataclass(frozen=True)
class Signature:
    slide_id: str
    score: float
    hist: tuple[float, ...] | None      # shape-type histogram, 5-dim
    edges: frozenset[int] | None        # x bins 0..11, y bins 12..19
    pbits: tuple[int, ...]              # 256 dhash bits of int(phash, 16)


def _bins(vals, n_bins: int, extent: float, offset: int) -> set[int]:
    out: set[int] = set()
    for v in vals or []:
        b = int(float(v) * n_bins / extent)
        out.add(offset + min(n_bins - 1, max(0, b)))
    return out


def _phash_bits(phash: str) -> tuple[int, ...]:
    try:
        h = int(phash or "0", 16)
    except ValueError:
        h = 0
    return tuple((h >> i) & 1 for i in range(PHASH_BITS))


def signature(rec: dict, score: float) -> Signature:
    stats = rec.get("shape_stats")
    hist: tuple[float, ...] | None = None
    edges: frozenset[int] | None = None
    if isinstance(stats, dict):
        n = float(stats.get("n_shapes") or 0)
        counts = (stats.get("n_textboxes") or 0,
                  stats.get("n_pictures") or 0,
                  stats.get("n_tables") or 0,
                  stats.get("n_charts") or 0,
                  stats.get("n_groups") or 0)
        hist = tuple(c / n for c in counts) if n else (0.0,) * 5
        edges = frozenset(
            _bins(stats.get("x_edges"), X_BINS, SLIDE_W_PT, 0)
            | _bins(stats.get("y_edges"), Y_BINS, SLIDE_H_PT, X_BINS))
    return Signature(slide_id=rec.get("slide_id", ""), score=score,
                     hist=hist, edges=edges,
                     pbits=_phash_bits(rec.get("phash", "")))


# --- centroids & distance -----------------------------------------------------

@dataclass
class _Centroid:
    hist_sum: list[float] = field(default_factory=lambda: [0.0] * 5)
    hist_n: int = 0
    edge_freq: dict[int, int] = field(default_factory=dict)
    edge_n: int = 0
    pbit_sum: list[float] = field(
        default_factory=lambda: [0.0] * PHASH_BITS)
    n: int = 0

    def add(self, sig: Signature) -> None:
        if sig.hist is not None:
            for i, v in enumerate(sig.hist):
                self.hist_sum[i] += v
            self.hist_n += 1
        if sig.edges is not None:
            for b in sig.edges:
                self.edge_freq[b] = self.edge_freq.get(b, 0) + 1
            self.edge_n += 1
        for i, b in enumerate(sig.pbits):
            self.pbit_sum[i] += b
        self.n += 1


def _cosine_dist(a, b) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 and nb == 0.0:
        return 0.0
    if na == 0.0 or nb == 0.0:
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    return 1.0 - dot / (na * nb)


def _jaccard_dist(bits: frozenset[int], cen: _Centroid) -> float:
    # Weighted jaccard vs centroid bin frequencies in [0, 1].
    keys = set(cen.edge_freq) | bits
    if not keys:
        return 0.0
    num = den = 0.0
    for k in keys:
        m = 1.0 if k in bits else 0.0
        c = cen.edge_freq.get(k, 0) / cen.edge_n if cen.edge_n else 0.0
        num += min(m, c)
        den += max(m, c)
    return 1.0 - num / den if den else 0.0


def _hamming_frac(pbits, cen: _Centroid) -> float:
    if not cen.n:
        return 0.0
    return sum(abs(b - s / cen.n)
               for b, s in zip(pbits, cen.pbit_sum)) / PHASH_BITS


def distance(sig: Signature, cen: _Centroid) -> float:
    parts: list[tuple[float, float]] = []
    if sig.hist is not None and cen.hist_n:
        mean = [s / cen.hist_n for s in cen.hist_sum]
        parts.append((W_HIST, _cosine_dist(sig.hist, mean)))
    if sig.edges is not None and cen.edge_n:
        parts.append((W_EDGE, _jaccard_dist(sig.edges, cen)))
    parts.append((W_PHASH, _hamming_frac(sig.pbits, cen)))
    total = sum(w for w, _ in parts)
    return sum(w * d for w, d in parts) / total


# --- greedy threshold clustering ------------------------------------------------

def greedy_cluster(sigs: list[Signature],
                   threshold: float = THRESHOLD
                   ) -> list[list[Signature]]:
    """Single deterministic pass: score desc (slide_id breaks ties),
    first centroid under the threshold wins, else a new cluster."""
    order = sorted(sigs, key=lambda s: (-s.score, s.slide_id))
    cents: list[_Centroid] = []
    members: list[list[Signature]] = []
    for sig in order:
        for i, cen in enumerate(cents):
            if distance(sig, cen) < threshold:
                members[i].append(sig)
                cen.add(sig)
                break
        else:
            cen = _Centroid()
            cen.add(sig)
            cents.append(cen)
            members.append([sig])
    return members


def cluster_records(members: list[list[Signature]]) -> list[ClusterRecord]:
    out: list[ClusterRecord] = []
    for i, mem in enumerate(members):
        ids = [s.slide_id for s in mem]  # already score-desc order
        out.append(ClusterRecord(
            cluster_id=f"c{i:03d}", slide_ids=ids,
            exemplar_slide_ids=ids[:MAX_EXEMPLARS], size=len(ids)))
    return out


# --- jsonl IO -----------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # Torn trailing line from a crashed upstream append: skip,
            # same tolerance as corpus/ingest.py — one lost row, never
            # a bricked pipeline.
            continue
    return rows


def load_signatures(work: Path) -> list[Signature]:
    index: dict[str, dict] = {}
    for row in _read_jsonl(work / "index.jsonl"):
        sid = row.get("slide_id")
        if sid:
            index[sid] = row  # append-only file: last line wins
    keep: dict[str, bool] = {}
    for row in _read_jsonl(work / "filtered.jsonl"):
        if row.get("slide_id"):
            keep[row["slide_id"]] = bool(row.get("keep"))
    scores: dict[str, float] = {}
    for row in _read_jsonl(work / "scores.jsonl"):
        if row.get("slide_id"):
            scores[row["slide_id"]] = float(row.get("score") or 0)
    sigs: list[Signature] = []
    for sid, row in index.items():
        # Missing verdict (or no filtered.jsonl yet) means keep: a torn
        # verdict line must never silently drop a slide.
        if not keep.get(sid, True):
            continue
        sigs.append(signature(row, scores.get(sid, 0.0)))
    return sigs


def run_cluster(work: str | Path, out: str | Path | None = None,
                threshold: float = THRESHOLD) -> dict:
    work = Path(work)
    out = Path(out) if out is not None else work / "clusters.jsonl"
    sigs = load_signatures(work)
    members = greedy_cluster(sigs, threshold)
    records = cluster_records(members)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(rec.model_dump_json() + "\n")
    sizes = Counter(r.size for r in records)
    return {"n_slides": len(sigs), "n_clusters": len(records),
            "sizes": {k: sizes[k] for k in sorted(sizes)}}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Cluster kept corpus slides into layout patterns.")
    ap.add_argument("--work",
                    default=str(Path(__file__).resolve().parent / "work"),
                    help="derived-data dir (default: corpus/work)")
    ap.add_argument("--out", default=None,
                    help="output jsonl (default: WORK/clusters.jsonl)")
    ap.add_argument("--threshold", type=float, default=THRESHOLD,
                    help="centroid distance to join a cluster")
    args = ap.parse_args(argv)
    summary = run_cluster(args.work, args.out, args.threshold)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
