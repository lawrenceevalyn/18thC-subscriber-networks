"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            overlap_network_viz.py
================================================================================
RUN WITH: python3 overlap_network_viz.py ../bipartite-graphs/outputs/graph.graphml
          python3 overlap_network_viz.py graph.graphml --output outputs/overlap-network.png

DESCRIPTION:
    A chord diagram of cross-work subscriber overlap. Each work is a node on
    a circle; an arced chord joins two works that share subscribers, its
    WIDTH set by the number of shared subscribers.

    Three choices keep it legible rather than a hairball:
      - Nodes are ordered around the circle by community (greedy modularity
        on Jaccard overlap), so works that overlap sit next to each other and
        their chords become short arcs near the rim instead of crossing lines.
        Community blocks are separated by small gaps.
      - Each node gets angular space proportional to its size, so large nodes
        don't collide; chords are drawn as curves bowing toward the center.
      - Node color = community; node size and the number inside each node =
        subscriber count; the title is set radially outside it.

    This view shows the raw magnitude of shared subscribers (chord width).
    To weigh an overlap against what chance would predict, the representation
    factor is available via _common.overlap(G, "repr").

    Both PNG and SVG versions are saved.

WHERE TO TWEAK:
    Almost every visual knob (fonts, sizes, colors, spacing, the manicule, the
    center title) lives in the "VISUAL SETTINGS" block just below the imports.
    Each constant has a comment saying what it does and which way to nudge it.
    The drawing code further down reads those constants and should rarely need
    editing for routine restyling.

--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.colors import to_rgb
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path as MplPath

import _common


# ===========================================================================
#                              VISUAL SETTINGS
#       Everything you'd reach for to restyle the figure lives here.
# ===========================================================================

# --- Center title + caption ------------------------------------------------
# Text shown on the white disc in the middle of the ring. Use "\n" for line
# breaks; both blocks are centered on the disc.
CENTER_TITLE = "Books\nlinked by\nsubscribers"
CENTER_CAPTION = (
    ""
)
CENTER_DISC_RADIUS = 0.5       # size of the white disc (data units; ring ≈ 1.0)
CENTER_DISC_ALPHA = 0.6        # disc opacity (1.0 = solid white, 0 = invisible)
CENTER_TITLE_Y = 0.00           # vertical position of the title on the disc
CENTER_TITLE_FONT_SIZE = 26
CENTER_CAPTION_Y = -0.17        # vertical position of the caption on the disc
CENTER_CAPTION_FONT_SIZE = 13
CENTER_CAPTION_COLOR = "#333333"

# --- Fonts -----------------------------------------------------------------
# Two families are loaded from the system font folders at draw time (see
# _register_fonts); assign each text element to one of them below.
DISPLAY_FONT = "Playfair Display"   # an elegant high-contrast serif
BODY_FONT = "Roboto"                # a clean sans, most legible when small
# Role assignments — set each to DISPLAY_FONT or BODY_FONT:
TITLE_FONT = DISPLAY_FONT           # the center title
LABEL_FONT = DISPLAY_FONT           # the radial work labels (surname + title)
COUNT_FONT = BODY_FONT              # the numbers inside nodes — sans reads
                                    #   most clearly at the small sizes they hit
CAPTION_FONT = BODY_FONT            # the center caption (and the default family)

# --- Radial labels (one per work, just outside the ring) -------------------
LABEL_FONT_SIZE = 18
LABEL_COLOR = "black"
LABEL_RADIUS = 1.16             # where labels start, measured from the ring
                                #   center (1.0 = on the node ring). Raise to
                                #   push labels further out from the nodes.

# --- Nodes + the subscriber count printed inside each one ------------------
# A node's AREA encodes its subscriber count, scaling linearly between
# NODE_AREA_MIN (the smallest work) and NODE_AREA_MAX (the largest). Areas are
# matplotlib scatter "s" values, i.e. points^2. Any node that would be too
# small to fit its own number is then grown just enough to fit it.
NODE_AREA_MIN = 160
NODE_AREA_MAX = 3400
NODE_MAX_LUMINANCE = 0.40       # community colors are darkened to at most this
                                #   brightness so white numerals read on them
                                #   without an outline (lower = darker nodes).
COUNT_FONT_SIZE = 15
COUNT_COLOR = "white"
COUNT_GLYPH_WIDTH = 0.62        # avg digit width as a fraction of font size,
                                #   used to estimate how wide a number is …
COUNT_FILL_RATIO = 0.70         # … and how much of a node's diameter it may
                                #   fill (0.70 = leave a 30% margin). Tune these
                                #   two if numbers look cramped or too loose.

# --- Node colors (the per-community palette) -------------------------------
# One color per community on a navy -> gray -> dark-purple spectrum, chosen to
# sit quietly beneath the brighter CHORD_COLOR. Communities are assigned colors
# by index (largest community first); the list cycles if there are more
# communities than colors. Works that share no readers (the "isolates") use
# ISOLATE_NODE_COLOR. Every color is darkened to NODE_MAX_LUMINANCE if needed so
# the white number still reads inside it.
NODE_PALETTE = [
    "#262536",   # dark purple (the anchor color)
    "#33314a",   # indigo-purple
    "#2b3a57",   # navy
    "#4c4960",   # mauve-gray
    "#3a4a6e",   # blue
    "#565664",   # purple-gray
]
ISOLATE_NODE_COLOR = "#5b5965"   # works sharing no subscribers (community -1)

# Alternative moods on the same spectrum — paste one over the two values above:
#   Balanced (navy main cluster, most contrast with the chords):
#     NODE_PALETTE = ["#2c3e5c", "#5e6170", "#262536", "#3f5476", "#4a4a57", "#34304a"]
#     ISOLATE_NODE_COLOR = "#6b6d77"
#   Navy-forward (cooler steel-blues throughout):
#     NODE_PALETTE = ["#22304f", "#41557a", "#2d2b41", "#6a6d7a", "#34324c", "#4e5a78"]
#     ISOLATE_NODE_COLOR = "#717480"

# --- Chords (the arcs joining works that share subscribers) ----------------
CHORD_COLOR = "#B370B0"
CHORD_ALPHA = 0.8
CHORD_WIDTH_MIN = 1.6           # line width for the fewest shared subscribers
CHORD_WIDTH_MAX = 8.6           # line width for the most shared subscribers
CHORD_WIDTH_FLAT = 3.0          # width used when every chord is equal
CHORD_BOW_BASE = 0.62           # how far chords bow toward the center; higher =
CHORD_BOW_FALLOFF = 0.47        #   deeper bow. Falloff shrinks the bow for
                                #   far-apart pairs so long chords don't sag.

# --- Ring layout / spacing -------------------------------------------------
# Nodes are placed clockwise from the top. Each gets angular room proportional
# to its radius; these fractions add breathing room on top of that.
NODE_GAP_FRACTION = 0.008       # gap between adjacent nodes in a community
COMMUNITY_GAP_FRACTION = 0.02   # larger gap between community blocks
SPACING_MARGIN = 0.98           # anti-overlap safety net: if the chosen node
                                # sizes would make ring-neighbors touch, every
                                # node (and its number) is shrunk uniformly
                                # until the tightest pair sits at this fraction
                                # of touching. Lower = more breathing room;
                                # 1.0 = allow nodes to just kiss. This only
                                # ever shrinks — it never grows nodes past the
                                # sizes set above, so to make nodes BIGGER
                                # raise NODE_AREA_* or FIGURE_SIZE_INCHES.

# --- Manicule (pointing hand that flags the motivating work) ---------------
# Drawn from the SVG in resources/; in its own coordinates the hand points
# rightward, and we scale + rotate it to aim at the highlighted work's label.
MANICULE_FILE = Path(__file__).parent / "resources" / "manicule.svg"
MANICULE_COLOR = "#262536"   # dark purple (the palette anchor)
MANICULE_LENGTH = 0.42          # fingertip-to-cuff span, in data units (bigger
                                #   = larger hand)
MANICULE_GAP = 0.05             # gap between the fingertip and the label's end
MANICULE_TILT_DEG = 0.0         # tilt the approach off the label's radial line
                                #   (0 = point straight down the label; +/- to
                                #   swing the hand to one side)

# --- Canvas / output -------------------------------------------------------
FIGURE_SIZE_INCHES = 16         # square figure side length
AXIS_LIMIT = 1.9                # half-width of the drawing area in data units;
                                # the ring has radius ~1, labels reach ~1.6,
                                # so 1.9 leaves a margin. Raise if labels clip.
OUTPUT_DPI = 150

# Stacking order (matplotlib "zorder", higher = drawn on top):
#   chords 1 · nodes 2 · labels 3 · counts 4 · center disc 7 · center text 8 ·
#   manicule 9. Adjust the literals in draw_network if you need to reorder.

# ===========================================================================
#                          END OF VISUAL SETTINGS
# ===========================================================================


def _register_fonts():
    """Register the bundled Roboto + Playfair Display variable fonts with
    matplotlib (they may not be in its cache) and make Roboto the default
    family. Returns the set of font names matplotlib now knows about."""
    font_dirs = ("~/Library/Fonts", "/Library/Fonts", "/System/Library/Fonts")
    file_stems = ("Roboto", "PlayfairDisplay")
    for directory in font_dirs:
        for stem in file_stems:
            pattern = os.path.join(os.path.expanduser(directory), f"{stem}*.ttf")
            for font_file in glob.glob(pattern):
                try:
                    fm.fontManager.addfont(font_file)
                except Exception:
                    pass  # unreadable/duplicate font file — skip it
    known_fonts = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["font.family"] = (
        BODY_FONT if BODY_FONT in known_fonts else "sans-serif")
    return known_fonts


def _is_highlighted(G, work, highlight_term):
    """True if `highlight_term` (case-insensitive) appears in the work's author
    surname or its book title — i.e. this is a work the manicule should flag."""
    if not highlight_term:
        return False
    term = highlight_term.lower()
    return (term in _common.author_last(G.nodes[work].get("author", "")).lower()
            or term in G.nodes[work].get("book", "").lower())


def community_order(works_sorted, membership):
    """Order works so each community forms a contiguous arc of the circle
    (communities largest-first, with works that share no readers placed last).
    Within a community the incoming year/book order is preserved."""
    members_by_community = defaultdict(list)
    for work in works_sorted:
        members_by_community[membership[work]].append(work)
    ordered_works = []
    for community in sorted(c for c in members_by_community if c >= 0):
        ordered_works.extend(members_by_community[community])
    ordered_works.extend(members_by_community.get(-1, []))  # isolates last
    return ordered_works


def _chord_curve(point_a, point_b, n_samples=48):
    """Sample a quadratic Bezier from `point_a` to `point_b` that bows toward
    the ring center. Even adjacent pairs bow well inward (so a chord between
    neighbors lifts off the rim and stays visible); far-apart pairs bow less so
    long chords don't sag through the middle."""
    point_a, point_b = np.asarray(point_a), np.asarray(point_b)
    separation = np.linalg.norm(point_a - point_b) / 2.0   # 0 adjacent .. 1 opposite
    bow = CHORD_BOW_BASE - CHORD_BOW_FALLOFF * separation   # control-point radius frac
    control = (point_a + point_b) / 1.5 * bow               # pull the midpoint inward
    t = np.linspace(0.0, 1.0, n_samples).reshape(-1, 1)
    return (1 - t) ** 2 * point_a + 2 * (1 - t) * t * control + t ** 2 * point_b


def _label_parts(G, work):
    """Return (author_surname, work_title) for a work's radial label. The title
    is set in italics and the surname in roman by _draw_radial_label."""
    title = _common.short_title(G.nodes[work].get("book", ""))
    surname = _common.author_last(G.nodes[work].get("author", ""))
    return surname, title


def _node_color(community_index):
    """Pick a community's fill from NODE_PALETTE (cycled), or the isolate gray
    for works that share no readers (community index < 0)."""
    if community_index < 0:
        return ISOLATE_NODE_COLOR
    return NODE_PALETTE[community_index % len(NODE_PALETTE)]


def _dark_fill(color, max_luminance=NODE_MAX_LUMINANCE):
    """Darken `color` toward black until its relative luminance is at most
    `max_luminance`, so white numerals read on it without a halo or a ring.
    Returns an (r, g, b) tuple in 0..1."""
    r, g, b = to_rgb(color)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if luminance > max_luminance:
        scale = max_luminance / luminance
        r, g, b = r * scale, g * scale, b * scale
    return (r, g, b)


def _fit_area(text, font_size):
    """Smallest scatter area (points^2) whose circle comfortably holds `text`
    at `font_size`. Used to grow undersized nodes so their number doesn't spill
    over the rim. See COUNT_GLYPH_WIDTH / COUNT_FILL_RATIO to tune the fit."""
    text_width_pts = font_size * COUNT_GLYPH_WIDTH * len(text)
    diameter_pts = text_width_pts / COUNT_FILL_RATIO   # widen to leave a margin
    return diameter_pts ** 2                            # scatter "s" ≈ diameter^2


# ===========================================================================
#   Manicule helpers: parse the hand SVG into a matplotlib Path, then scale,
#   rotate and place it so its fingertip points at a chosen spot.
# ===========================================================================

# Matches one SVG-path token at a time: either a command letter or a number
# (handles leading +/-, a bare leading dot like ".5", and exponents).
_SVG_PATH_TOKEN = re.compile(
    r"[MmCcLlHhVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _svg_path_to_mpl(path_data):
    """Convert an SVG path 'd' string (the manicule uses only the m/c/l/h/v/z
    commands) into a matplotlib Path. SVG's y-axis points down, so we flip y to
    leave the hand upright in matplotlib's y-up axis coordinates."""
    tokens = _SVG_PATH_TOKEN.findall(path_data)
    vertices, codes = [], []
    i, command = 0, None
    current = np.zeros(2)          # pen position
    subpath_start = np.zeros(2)    # where the current subpath began (for 'z')

    def next_number():
        nonlocal i
        value = float(tokens[i]); i += 1
        return value

    while i < len(tokens):
        if tokens[i].isalpha():               # a new command letter
            command = tokens[i]; i += 1
        is_relative, kind = command.islower(), command.lower()

        if kind == "m":                        # moveto
            point = (current + (next_number(), next_number())
                     if is_relative else np.array([next_number(), next_number()]))
            current = subpath_start = point
            vertices.append(point.copy()); codes.append(MplPath.MOVETO)
            command = "l" if is_relative else "L"   # extra pairs after m = lineto
        elif kind == "l":                      # lineto
            point = (current + (next_number(), next_number())
                     if is_relative else np.array([next_number(), next_number()]))
            current = point
            vertices.append(point.copy()); codes.append(MplPath.LINETO)
        elif kind == "h":                      # horizontal lineto
            x = next_number()
            point = np.array([current[0] + x if is_relative else x, current[1]])
            current = point
            vertices.append(point.copy()); codes.append(MplPath.LINETO)
        elif kind == "v":                      # vertical lineto
            y = next_number()
            point = np.array([current[0], current[1] + y if is_relative else y])
            current = point
            vertices.append(point.copy()); codes.append(MplPath.LINETO)
        elif kind == "c":                      # cubic Bezier (2 controls + end)
            ctrl1 = (current + (next_number(), next_number())
                     if is_relative else np.array([next_number(), next_number()]))
            ctrl2 = (current + (next_number(), next_number())
                     if is_relative else np.array([next_number(), next_number()]))
            end = (current + (next_number(), next_number())
                   if is_relative else np.array([next_number(), next_number()]))
            vertices += [ctrl1, ctrl2, end]; codes += [MplPath.CURVE4] * 3
            current = end
        elif kind == "z":                      # close subpath
            vertices.append(subpath_start.copy()); codes.append(MplPath.CLOSEPOLY)
            current = subpath_start.copy()
        else:
            raise ValueError(f"unsupported SVG path command {command!r}")

    verts = np.array(vertices)
    verts[:, 1] = -verts[:, 1]                 # flip SVG y-down to matplotlib y-up
    return MplPath(verts, codes)


def _load_manicule():
    """Parse the manicule SVG once and return (path, fingertip). In its own
    coordinates the hand points along +x, so the fingertip is its right-most
    vertex; _draw_manicule rotates from there to wherever we want to point."""
    root = ET.parse(MANICULE_FILE).getroot()
    path_data = next(el.attrib["d"] for el in root.iter() if el.tag.endswith("path"))
    path = _svg_path_to_mpl(path_data)
    fingertip = path.vertices[np.argmax(path.vertices[:, 0])]   # right-most point
    return path, fingertip


def _text_data_length(ax, text, font_size, style="normal", family=None):
    """Width, in data (axis) units, that `text` would occupy along its baseline
    at the given size. Used to lay out the two-part labels and locate their
    outer ends. `family=None` inherits the default body font (Roboto).

    It works by drawing an invisible probe, measuring it in pixels, then
    converting that pixel width back into data units via the axis transform."""
    figure = ax.figure
    renderer = figure.canvas.get_renderer()
    text_kwargs = dict(fontsize=font_size, style=style, alpha=0)
    if family:
        text_kwargs["family"] = family
    probe = ax.text(0, 0, text, **text_kwargs)
    width_px = probe.get_window_extent(renderer).width
    probe.remove()
    data_from_px = ax.transData.inverted()
    (x_start, _), (x_end, _) = data_from_px.transform((0, 0)), data_from_px.transform((width_px, 0))
    return abs(x_end - x_start)


def _draw_radial_label(ax, radial, angle_deg, surname, title, font_size, color):
    """Draw one work's label just outside the rim, along its radius: a roman
    author surname followed by an italic work title. Returns the data-coord
    point at the label's OUTER end (used to aim the manicule).

    `radial` is the work's unit position vector; the label is anchored at
    `radial * LABEL_RADIUS` and runs outward from there. On the left half of
    the circle the text is flipped 180 so it stays right-way-up, which swaps
    the inner/outer order of the surname and title."""
    on_left_half = radial[0] < 0
    rotation = angle_deg + 180 if on_left_half else angle_deg
    align = "right" if on_left_half else "left"
    anchor = radial * LABEL_RADIUS
    shared_kwargs = dict(rotation=rotation, rotation_mode="anchor", va="center",
                         fontsize=font_size, color=color, family=LABEL_FONT, zorder=3)

    title_width = _text_data_length(ax, title, font_size, style="italic", family=LABEL_FONT)
    if not surname:                              # title only, no author
        ax.text(*anchor, title, ha=align, style="italic", **shared_kwargs)
        return anchor + title_width * radial

    surname_text = f"{surname}, "
    surname_width = _text_data_length(ax, surname_text, font_size, family=LABEL_FONT)
    if not on_left_half:                         # right half: surname inner, title outer
        ax.text(*anchor, surname_text, ha=align, style="normal", **shared_kwargs)
        ax.text(*(anchor + surname_width * radial), title,
                ha=align, style="italic", **shared_kwargs)
    else:                                        # left half: title inner, surname outer
        ax.text(*anchor, title, ha=align, style="italic", **shared_kwargs)
        ax.text(*(anchor + title_width * radial), surname_text,
                ha=align, style="normal", **shared_kwargs)
    return anchor + (surname_width + title_width) * radial


def _draw_manicule(ax, path, fingertip, tip, aim, length, zorder):
    """Place the manicule so its fingertip lands at `tip` and the finger points
    along the unit vector `aim`, scaled so the hand spans `length` data units
    fingertip-to-cuff. The hand is drawn with clipping off so it can extend
    past the axes box into the figure margin, the way the text labels do."""
    xs = path.vertices[:, 0]
    scale = length / (xs.max() - xs.min())       # native width -> desired length
    aim_angle = np.arctan2(aim[1], aim[0])       # native hand points +x (angle 0)
    rotation = np.array([[np.cos(aim_angle), -np.sin(aim_angle)],
                         [np.sin(aim_angle),  np.cos(aim_angle)]])
    # Center on the fingertip, scale, rotate to the aim, then move to `tip`.
    placed_verts = ((path.vertices - fingertip) * scale) @ rotation.T + tip
    patch = PathPatch(MplPath(placed_verts, path.codes),
                      facecolor=MANICULE_COLOR, edgecolor="none", zorder=zorder)
    patch.set_clip_on(False)                     # allow it past the axes box
    ax.add_patch(patch)


def draw_network(G, resolution, output_path, highlight=""):
    # --- Data prep: communities, counts, which works to flag ---------------
    # Communities (used for node ordering + color) are detected on Jaccard
    # overlap; chord width uses raw shared-subscriber counts.
    works_sorted, sets, population, pairs = _common.overlap(G, "jaccard")
    if len(works_sorted) < 2:
        print("  WARNING: fewer than two works; nothing to draw.")
        return

    overlap_graph = _common.projected_overlap_graph(works_sorted, sets, pairs)
    membership = _common.detect_communities(overlap_graph, resolution=resolution)
    works = community_order(works_sorted, membership)
    counts = {work: len(sets[work]) for work in works}
    highlighted = {work for work in works if _is_highlighted(G, work, highlight)}
    if highlight:
        print(f"  Highlighting {len(highlighted)} work(s) matching {highlight!r}.")

    # Build the chord list: one (a, b, shared) per pair that shares readers.
    edges = []
    for work_a, work_b in pairs:
        shared = len(sets[work_a] & sets[work_b])
        if shared > 0:
            edges.append((work_a, work_b, shared))
    if not edges:
        print("  WARNING: no shared subscribers between any works; nothing to draw.")
        return

    # Map a shared-subscriber count to a chord line width.
    min_shared = min(shared for _, _, shared in edges)
    max_shared = max(shared for _, _, shared in edges)

    def chord_width(shared):
        if max_shared == min_shared:
            return CHORD_WIDTH_FLAT
        fraction = (shared - min_shared) / (max_shared - min_shared)
        return CHORD_WIDTH_MIN + (CHORD_WIDTH_MAX - CHORD_WIDTH_MIN) * fraction

    # --- Node sizes: area encodes count, but never smaller than its number --
    max_count = max(counts.values())
    counts_str = {work: f"{counts[work]:,}" for work in works}   # comma-grouped
    node_size = {
        work: max(
            NODE_AREA_MIN + (NODE_AREA_MAX - NODE_AREA_MIN) * (counts[work] / max_count),
            _fit_area(counts_str[work], COUNT_FONT_SIZE),
        )
        for work in works
    }

    # --- Ring layout: an angle for every node ------------------------------
    # Walk the works in community order, handing each an angular slice whose
    # width is proportional to the node's radius (so big nodes don't collide).
    # Insert a small gap between nodes and a larger gap between communities,
    # including the wrap-around gap across the top of the circle.
    node_radius = {work: np.sqrt(node_size[work]) for work in works}
    radius_sum = sum(node_radius.values())
    node_gap = radius_sum * NODE_GAP_FRACTION
    community_gap = radius_sum * COMMUNITY_GAP_FRACTION

    # `segments` is the sequence of slices around the ring: (work, width) for a
    # node, or (None, width) for a gap.
    segments, prev_community = [], None
    for work in works:
        if prev_community is not None:
            same_community = membership[work] == prev_community
            segments.append((None, node_gap if same_community else community_gap))
        segments.append((work, node_radius[work]))
        prev_community = membership[work]
    if membership[works[0]] != membership[works[-1]]:
        segments.append((None, community_gap))   # gap where the ring wraps at top

    # Convert cumulative slice widths into angles, going clockwise from the top
    # (pi/2). Each node sits at the center of its slice.
    total_weight = sum(width for _, width in segments)
    node_angle, angle_cursor = {}, 0.0
    for work, width in segments:
        if work is not None:
            node_angle[work] = np.pi / 2 - 2 * np.pi * (angle_cursor + width / 2) / total_weight
        angle_cursor += width
    node_pos = {work: np.array([np.cos(node_angle[work]), np.sin(node_angle[work])])
                for work in works}

    # --- Canvas ------------------------------------------------------------
    _register_fonts()
    fig, ax = plt.subplots(figsize=(FIGURE_SIZE_INCHES, FIGURE_SIZE_INCHES))
    ax.set_xlim(-AXIS_LIMIT, AXIS_LIMIT)
    ax.set_ylim(-AXIS_LIMIT, AXIS_LIMIT)
    ax.set_aspect("equal")
    ax.axis("off")

    # --- Keep nodes from overlapping ---------------------------------------
    # The angles above depend only on the RELATIVE node sizes, so shrinking
    # every node by one uniform factor moves none of them — it just opens space
    # between them. Here we find the tightest pair of ring-neighbors (in real
    # data units, via the axes transform) and, if they'd overlap, shrink all
    # nodes — and their numbers — by the factor that restores a SPACING_MARGIN
    # gap. When the nodes already fit, the factor is 1.0 and nothing changes.
    to_data = ax.transData.inverted()
    data_origin = to_data.transform((0.0, 0.0))
    px_per_point = fig.dpi / 72.0                       # 72 points per inch
    data_per_point = abs(to_data.transform((px_per_point, 0.0))[0] - data_origin[0])
    # A scatter marker of area s (points^2) renders ~sqrt(s) points across.
    node_radius_data = {w: np.sqrt(node_size[w]) * data_per_point / 2.0 for w in works}

    ring_order = [w for w, _ in segments if w is not None]
    tightest_ratio = 1.0                                # center-gap ÷ radii-sum
    for i in range(len(ring_order)):
        near, far = ring_order[i], ring_order[(i + 1) % len(ring_order)]
        center_gap = float(np.linalg.norm(node_pos[near] - node_pos[far]))
        radii_sum = node_radius_data[near] + node_radius_data[far]
        if radii_sum > 0:
            tightest_ratio = min(tightest_ratio, center_gap / radii_sum)

    node_scale = min(1.0, tightest_ratio * SPACING_MARGIN)   # linear; never > 1
    if node_scale < 1.0:
        print(f"  Nodes would overlap; shrinking them to {node_scale:.0%} to fit.")
    node_size = {w: node_size[w] * node_scale ** 2 for w in works}  # area ∝ linear²
    count_font_size = COUNT_FONT_SIZE * node_scale       # numbers shrink in step

    # --- Chords (drawn first, thin ones underneath) ------------------------
    for work_a, work_b, shared in sorted(edges, key=lambda e: e[2]):
        curve = _chord_curve(node_pos[work_a], node_pos[work_b])
        ax.plot(curve[:, 0], curve[:, 1], color=CHORD_COLOR,
                linewidth=chord_width(shared), alpha=CHORD_ALPHA, zorder=1,
                solid_capstyle="round")

    # --- Nodes + their subscriber counts -----------------------------------
    # Community colors are darkened so the white count reads on them without an
    # outline or halo; the count itself is set in Playfair Display.
    for work in works:
        ax.scatter(*node_pos[work], s=node_size[work],
                   c=[_dark_fill(_node_color(membership[work]))],
                   edgecolors="none", linewidths=0, zorder=2)
        ax.annotate(counts_str[work], node_pos[work], ha="center", va="center",
                    fontsize=count_font_size, color=COUNT_COLOR,
                    family=COUNT_FONT, fontweight="bold", zorder=4)

    # --- Radial labels (roman surname, italic title) -----------------------
    # Keep each label's outer-end point so the manicule can aim at it.
    label_end = {}
    for work in works:
        surname, title = _label_parts(G, work)
        label_end[work] = _draw_radial_label(
            ax, node_pos[work], np.degrees(node_angle[work]),
            surname, title, LABEL_FONT_SIZE, LABEL_COLOR)

    # --- Manicule pointing at the highlighted work -------------------------
    # Rather than recoloring the motivating work, set a pointing hand just past
    # the outer end of its label, with the hand extending further out — so it
    # draws the eye without hiding the node, its number, or its title.
    if highlighted:
        manicule_path, fingertip = _load_manicule()
        tilt_rad = np.radians(MANICULE_TILT_DEG)
        tilt = np.array([[np.cos(tilt_rad), -np.sin(tilt_rad)],
                         [np.sin(tilt_rad),  np.cos(tilt_rad)]])
        for work in highlighted:
            approach_dir = tilt @ node_pos[work]          # outward, tilted off radial
            tip = label_end[work] + approach_dir * MANICULE_GAP   # just past the label
            _draw_manicule(ax, manicule_path, fingertip, tip,
                           aim=-approach_dir, length=MANICULE_LENGTH, zorder=9)

    # --- Center title + caption on a soft white disc -----------------------
    # The disc sits over the chords that bow through the middle so the text
    # stays readable against them.
    ax.add_patch(Circle((0, 0), CENTER_DISC_RADIUS, facecolor="white",
                        alpha=CENTER_DISC_ALPHA, edgecolor="none", zorder=7))
    ax.text(0, CENTER_TITLE_Y, CENTER_TITLE, ha="center", va="center",
            fontsize=CENTER_TITLE_FONT_SIZE, family=TITLE_FONT,
            fontweight="bold", color="black", linespacing=1.15, zorder=8)
    ax.text(0, CENTER_CAPTION_Y, CENTER_CAPTION, ha="center", va="center",
            fontsize=CENTER_CAPTION_FONT_SIZE, color=CENTER_CAPTION_COLOR,
            fontstyle="italic", linespacing=1.4, zorder=8)

    _common.save_figure(fig, output_path, dpi=OUTPUT_DPI)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Draw cross-work subscriber overlap as a chord diagram."
    )
    parser.add_argument("input_graphml",
                        help="Path to the GraphML file (from build_graph.py).")
    parser.add_argument("--output", default="outputs/overlap-network.png",
                        help="Output path (default: outputs/overlap-network.png).")
    parser.add_argument("--resolution", type=float, default=1.0,
                        help="Community-detection resolution for node ordering "
                             "(>1 = more, smaller clusters; default: 1.0).")
    parser.add_argument("--highlight", default="",
                        help="Point a manicule (pointing hand) at the work "
                             "matching this author surname or book title.")
    args = parser.parse_args()

    input_path = Path(args.input_graphml)
    if not input_path.is_file():
        print(f"ERROR: {input_path} is not a file.")
        sys.exit(1)

    G = _common.load_graph(input_path)
    print(f"Loaded graph: {len(_common.work_nodes(G))} works, "
          f"{len(_common.subscriber_nodes(G))} subscribers, "
          f"{G.number_of_edges()} edges")
    print("Drawing chord (width = shared subscribers)...")
    draw_network(G, args.resolution, args.output, highlight=args.highlight)
    print("Done.")


if __name__ == "__main__":
    main()
