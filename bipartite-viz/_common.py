"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                                _common.py
================================================================================
DESCRIPTION:
    Shared helpers for the bipartite-viz programs. This is the single
    source of truth for:

        - reading the GraphML graph and pulling out work / subscriber nodes
        - the book color palette and abbreviation scheme (so a book looks
          the same in every figure)
        - saving a figure as both PNG and SVG
        - the cross-work overlap measures: shared-subscriber count,
          Jaccard similarity, and representation factor (overlap relative
          to what the two list sizes would predict by chance)

    Each visualization is a small standalone program that imports from
    here; this module renders nothing on its own.
--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import csv
import hashlib
import re
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import Normalize, TwoSlopeNorm


# ---------------------------------------------------------------------------
# Graph IO
# ---------------------------------------------------------------------------

def load_graph(graphml_path):
    """Read the GraphML graph, restoring the integer `bipartite` flag."""
    G = nx.read_graphml(graphml_path)
    for node in G.nodes:
        G.nodes[node]["bipartite"] = int(G.nodes[node]["bipartite"])
    return G


def work_nodes(G):
    return [n for n, d in G.nodes(data=True) if d["bipartite"] == 0]


def subscriber_nodes(G):
    return [n for n, d in G.nodes(data=True) if d["bipartite"] == 1]


def _year_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def sort_works(G, works=None):
    """Order works by earliest publication year, then title."""
    if works is None:
        works = work_nodes(G)
    return sorted(
        works,
        key=lambda n: (_year_int(G.nodes[n].get("first_year")),
                       G.nodes[n].get("book", "")),
    )


# ---------------------------------------------------------------------------
# Book color + label conventions (one source of truth)
# ---------------------------------------------------------------------------

# Explicit colors for the headline works; any other book gets a stable
# color hashed from its title (deterministic and independent of which
# books happen to appear in a given figure).
BOOK_COLOR = {
    "Interesting Narrative": "#c84634",
    "Thoughts and Sentiments": "#1f7a8c",
    "Letters": "#5d3a8e",
}

BOOK_ABBR = {
    "Interesting Narrative": "IN",
    "Thoughts and Sentiments": "T&S",
    "Letters": "Ltrs",
}

# A 20-color qualitative palette (matplotlib tab20) for unlisted books.
_PALETTE = [
    "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#4C4A6C",
    "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5",
    "#8c564b", "#c49c94", "#e377c2", "#f7b6d2", "#7f7f7f",
    "#c7c7c7", "#bcbd22", "#dbdb8d", "#17becf", "#9edae5",
]

_SKIP_WORDS = {"a", "an", "the", "of", "in", "on", "to", "for"}


def book_color(book):
    if book in BOOK_COLOR:
        return BOOK_COLOR[book]
    h = int(hashlib.md5(book.encode("utf-8")).hexdigest(), 16)
    return _PALETTE[h % len(_PALETTE)]


_SHORT_TITLE_CSV = Path(__file__).resolve().parent / "resources" / "short-titles.csv"
_short_title_overrides = None


def _load_short_title_overrides():
    """Curated full-title -> short-title map from resources/short-titles.csv.
    Rows with a blank short_title are ignored (fall through to the heuristic).
    Cached after first load."""
    global _short_title_overrides
    if _short_title_overrides is None:
        _short_title_overrides = {}
        if _SHORT_TITLE_CSV.is_file():
            with open(_SHORT_TITLE_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    book = (row.get("book") or "").strip()
                    short = (row.get("short_title") or "").strip()
                    if book and short:
                        _short_title_overrides[book] = short
    return _short_title_overrides


def short_title(book, max_len=24):
    """A readable short form of a book title for on-figure labels.

    A curated override in resources/short-titles.csv wins if present;
    otherwise a heuristic applies:
      1. drop a leading article ("The Letters" -> "Letters")
      2. cut at the first comma ("Ethics, Rational and Theological" -> "Ethics")
      3. if still long, trim to whole words within max_len, dropping trailing
         filler so the ellipsis lands on a meaningful word.
    Unlike book_abbr (initials), this stays human-readable.
    """
    override = _load_short_title_overrides().get(book.strip())
    if override:
        return override
    title = re.sub(r"^(the|an|a)\s+", "", book.strip(), flags=re.IGNORECASE)
    if "," in title:
        title = title.split(",")[0].strip()
    if len(title) <= max_len:
        return title
    kept = []
    for word in title.split():
        if len(" ".join(kept)) + len(word) + 1 > max_len:
            break
        kept.append(word)
    while kept and kept[-1].lower() in _SKIP_WORDS:
        kept.pop()
    text = " ".join(kept) or title[:max_len].rstrip()
    return text.rstrip(",;:") + "…"


def author_last(author):
    """Best-effort author surname for a label. Handles 'Last, First' and
    'First Last'; returns '' when unknown."""
    a = (author or "").strip()
    if not a:
        return ""
    if "," in a:
        return a.split(",")[0].strip()
    return a.split()[-1]


def book_abbr(book):
    """Short label for a book: explicit override, else initials of the
    significant words ('Thoughts and Sentiments' -> 'T&S')."""
    if book in BOOK_ABBR:
        return BOOK_ABBR[book]
    words = book.split()
    significant = [w for w in words if w.lower() not in _SKIP_WORDS]
    if len(significant) <= 1:
        return book
    parts = []
    for w in words:
        if w.lower() == "and":
            parts.append("&")
        elif w.lower() not in _SKIP_WORDS:
            parts.append(w[0].upper())
    return "".join(parts)


# ---------------------------------------------------------------------------
# Figure saving
# ---------------------------------------------------------------------------

def save_figure(fig, output_path, dpi=200, transparent=True, **savefig_kwargs):
    """Save `fig` to `output_path` and also to the sibling PNG/SVG file.
    Transparent background by default, so figures drop cleanly onto slides
    or pages of any color."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(output_path, dpi=dpi, transparent=transparent, **savefig_kwargs)
    print(f"  Saved {output_path}")

    suffix = output_path.suffix.lower()
    alt_suffix = ".svg" if suffix == ".png" else ".png"
    alt_path = output_path.with_suffix(alt_suffix)
    fig.savefig(alt_path, dpi=dpi, transparent=transparent, **savefig_kwargs)
    print(f"  Saved {alt_path}")


# ---------------------------------------------------------------------------
# Cross-work overlap measures
# ---------------------------------------------------------------------------

MEASURES = ("repr", "count", "jaccard")

MEASURE_LABEL = {
    "repr": "representation factor",
    "count": "shared subscribers",
    "jaccard": "Jaccard similarity",
}


def measure_cmap_norm(measure, values):
    """Pick a colormap + normalization suited to a measure's value range.

    Representation factor diverges around 1.0 (the chance baseline): blue
    below, red above. Count and Jaccard are sequential from zero upward.
    """
    vals = list(values)
    vmax = max(vals) if vals else 1.0
    vmin = min(vals) if vals else 0.0
    if measure == "repr":
        hi = max(vmax, 1.0001)
        norm = TwoSlopeNorm(vmin=min(vmin, 0.999), vcenter=1.0, vmax=hi)
        return cm.RdBu_r, norm
    return cm.YlOrRd, Normalize(vmin=min(vmin, 0.0), vmax=max(vmax, 1e-9))


def subscriber_sets(G, works=None):
    """Map each work to the set of subscriber nodes attached to it."""
    if works is None:
        works = work_nodes(G)
    sets = {}
    for w in works:
        sets[w] = {
            n for n in G.neighbors(w) if G.nodes[n]["bipartite"] == 1
        }
    return sets


def subscriber_counts(G, works=None):
    return {w: len(s) for w, s in subscriber_sets(G, works).items()}


def overlap(G, measure="repr", works=None):
    """Pairwise cross-work overlap.

    Returns (works, sets, population, pairs) where `pairs` maps each
    unordered pair (a, b) with a < b in `works` order to its measure:

        count   - number of shared subscribers
        jaccard - |A n B| / |A u B|
        repr    - representation factor: observed shared subscribers
                  divided by the count expected if the two lists drew
                  independently from the whole subscriber population
                  (|A| * |B| / N). >1 means the works share more readers
                  than their sizes alone would predict; <1 means fewer.
    """
    if measure not in MEASURES:
        raise ValueError(f"unknown measure {measure!r}; pick one of {MEASURES}")

    works = sort_works(G, works)
    sets = subscriber_sets(G, works)
    population = len(subscriber_nodes(G))

    pairs = {}
    for i in range(len(works)):
        for j in range(i + 1, len(works)):
            a, b = works[i], works[j]
            A, B = sets[a], sets[b]
            shared = len(A & B)
            if measure == "count":
                val = float(shared)
            elif measure == "jaccard":
                union = len(A | B)
                val = shared / union if union else 0.0
            else:  # repr
                expected = (len(A) * len(B) / population) if population else 0.0
                val = (shared / expected) if expected > 0 else 0.0
            pairs[(a, b)] = val

    return works, sets, population, pairs


# ---------------------------------------------------------------------------
# Community structure (used by the chord diagram)
# ---------------------------------------------------------------------------

# Distinct colors for multi-work communities; works that share no readers
# (community index -1) are drawn in the site's light lavender-gray.
# Palette inspired by lawrenceevalyn.com — anchored on its muted purples
# (#4c4a6c, #393751) with harmonious cool tones and two restrained warm
# accents, all mid-dark so the white subscriber count reads inside.
CLUSTER_COLORS = [
    "#4c4a6c",  # site purple (primary / largest community)
    "#3f6f99",  # muted blue
    "#3f8a82",  # dusty teal
    "#8a5a86",  # muted plum
    "#b0883e",  # muted ochre (warm accent)
    "#6f5b9c",  # violet
    "#a85f74",  # dusty rose (warm accent)
    "#5f8a5a",  # muted green
    "#393751",  # site dark indigo
    "#7a8fb0",  # pale slate blue
]
ISOLATE_COLOR = "#d3d3da"


def community_color(idx):
    return ISOLATE_COLOR if idx < 0 else CLUSTER_COLORS[idx % len(CLUSTER_COLORS)]


def projected_overlap_graph(works, sets, pairs):
    """Weighted work-work graph: an edge per pair that shares a subscriber,
    weighted by the overlap measure. All works are added as nodes, so works
    that share no readers appear as isolated nodes."""
    G = nx.Graph()
    G.add_nodes_from(works)
    for (a, b), val in pairs.items():
        if sets[a] & sets[b] and val > 0:
            G.add_edge(a, b, weight=val)
    return G


def detect_communities(proj, resolution=1.0):
    """Return {node: community_index}. Multi-node communities are indexed
    0..k-1 by size (largest first); single-node communities share index -1.

    resolution > 1 favors more, smaller communities (splitting large blobs
    into finer sub-clusters); < 1 favors fewer, larger ones."""
    if proj.number_of_edges() == 0:
        return {n: -1 for n in proj.nodes()}
    try:
        comms = greedy_modularity_communities(proj, weight="weight",
                                              resolution=resolution)
    except TypeError:  # older networkx without the resolution parameter
        comms = greedy_modularity_communities(proj, weight="weight")
    comms = sorted(comms, key=len, reverse=True)
    membership = {}
    idx = 0
    for c in comms:
        if len(c) >= 2:
            for n in c:
                membership[n] = idx
            idx += 1
        else:
            for n in c:
                membership[n] = -1
    return membership
