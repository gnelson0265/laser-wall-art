"""Smooth source centerlines once while constructing an organic master."""
import numpy as np
from PIL import Image, ImageDraw
from scipy.interpolate import splprep, splev


def graph_paths(skeleton, breakpoints=None):
    from .reference_layers import neighbors
    nodes = {tuple(p): neighbors(skeleton, tuple(p)) for p in np.argwhere(skeleton)}
    visited, paths = set(), []
    def edge(a, b):
        return tuple(sorted((a, b)))
    breakpoints = breakpoints or set()
    starts = [p for p, ns in nodes.items() if len(ns) != 2 or p in breakpoints]
    for start in starts + list(nodes):
        for nxt in nodes[start]:
            if edge(start, nxt) in visited:
                continue
            path, previous, here = [start, nxt], start, nxt
            visited.add(edge(start, nxt))
            while len(nodes[here]) == 2 and here not in breakpoints:
                options = [p for p in nodes[here] if p != previous]
                following = options[0]
                if edge(here, following) in visited:
                    break
                visited.add(edge(here, following))
                path.append(following)
                previous, here = here, following
                if here == start:
                    break
            paths.append(path)
    return paths


def raster_smooth_centerlines(skeleton, size, padding):
    """Fit smooth organic curves to existing branches; hold junctions fixed."""
    width, height = size
    sx, sy = width / skeleton.shape[1], height / skeleton.shape[0]
    image = Image.new('1', (width + 2*padding, height + 2*padding))
    draw = ImageDraw.Draw(image)
    for path in graph_paths(skeleton):
        points = np.asarray(path, dtype=float)
        if len(points) >= 5:
            closed = np.array_equal(points[0], points[-1])
            spline, _ = splprep(points.T, s=len(points)*.12, k=3, per=closed)
            t = np.linspace(0, 1, max(12, int(len(points)*max(sx, sy)*2)))
            smooth = np.asarray(splev(t, spline)).T
            if not closed:
                smooth += ((1-t)[:, None]*(points[0]-smooth[0]) +
                           t[:, None]*(points[-1]-smooth[-1]))
            points = smooth
        xy = [(float((x+.5)*sx-.5+padding), float((y+.5)*sy-.5+padding)) for y, x in points]
        draw.line(xy, fill=1, width=1)
    mask = np.asarray(image).copy()
    half = mask[:, :mask.shape[1]//2]
    return np.concatenate((half, half[:, ::-1]), axis=1)
