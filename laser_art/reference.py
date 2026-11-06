"""Prepare one reference-derived master for visual approval, not a layer set.

No image generation or subject renderer is involved. The source's connected
artwork is thresholded, mirrored, scaled once, and locally reinforced around
its skeleton. Further layers require component decomposition of this master.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from .engine import boundary_mask
from .model import Manufacturing


def thin(mask):
    """Zhang–Suen thinning. Retain the topology of an 8-connected binary mask."""
    a = np.pad(mask.astype(bool), 1)
    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            p = a[1:-1, 1:-1]
            neighbors = [a[:-2, 1:-1], a[:-2, 2:], a[1:-1, 2:], a[2:, 2:],
                         a[2:, 1:-1], a[2:, :-2], a[1:-1, :-2], a[:-2, :-2]]
            count = sum(n.astype(np.uint8) for n in neighbors)
            transitions = sum((~neighbors[i] & neighbors[(i + 1) % 8]).astype(np.uint8)
                              for i in range(8))
            n, e, s, w = (neighbors[i] for i in (0, 2, 4, 6))
            if phase == 0:
                safe = ~(n & e & s) & ~(e & s & w)
            else:
                safe = ~(n & e & w) & ~(n & s & w)
            remove = p & (count >= 2) & (count <= 6) & (transitions == 1) & safe
            if remove.any():
                p[remove] = False
                changed = True
    return a[1:-1, 1:-1]


def artwork_from_reference(image):
    black = np.asarray(image.convert('L')) < 128
    labels, _ = ndi.label(black)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    # A supplied registration frame is a separate component spanning most of
    # the source canvas. Exclude it by bounding-box extent, not label ordering.
    candidates = []
    for label in np.argsort(sizes)[::-1]:
        if not sizes[label]:
            continue
        y, x = np.where(labels == label)
        frame = (x.max() - x.min() > black.shape[1] * .95 and
                 y.max() - y.min() > black.shape[0] * .95)
        if not frame:
            candidates.append(int(label))
            break
    if not candidates:
        raise ValueError('No separate artwork component found outside the source frame.')
    art = labels == candidates[0]
    if art.shape[1] % 2:
        raise ValueError('Reference needs an even width for the fixed central mirror axis.')
    half = art[:, :art.shape[1] // 2]
    art = np.concatenate((half, half[:, ::-1]), axis=1)
    y, x = np.where(art)
    crop = [int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1]
    return art[crop[1]:crop[3], crop[0]:crop[2]], crop


def prepare_reference(source, output, smooth=False):
    source, output = Path(source), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory; existing proofs are preserved.')
    with Image.open(source) as image:
        source_size = image.size
        native, crop = artwork_from_reference(image)
    skeleton = thin(native)
    skeleton |= skeleton[:, ::-1].copy()
    if ndi.label(skeleton, structure=np.ones((3, 3)))[1] != 1:
        raise ValueError('Source skeleton is disconnected; inspect the reference before continuing.')
    settings = Manufacturing()
    height = 6000
    width = 2 * round(native.shape[1] * height / native.shape[0] / 2)
    if width > 5500:
        width = 5500
        height = round(native.shape[0] * width / native.shape[1])
    size = (width, height)
    raw_image = Image.fromarray(native.astype(np.uint8)*255)
    raw = np.asarray(raw_image.resize(size, Image.Resampling.LANCZOS if smooth else Image.Resampling.NEAREST)) >= 128
    skel = np.asarray(Image.fromarray(skeleton).resize(size, Image.Resampling.NEAREST))
    radius = settings.radius
    # Leave room for reinforcement outside the source's tight artwork crop.
    # Without background padding, extremal strokes would be clipped.
    padding = radius + 3
    raw = np.pad(raw, padding)
    if smooth:
        from .smooth import raster_smooth_centerlines
        skel = raster_smooth_centerlines(skeleton, size, padding)
    else:
        skel = np.pad(skel, padding)
    height, width = raw.shape
    # Preserve broad original strokes by opening with the same disk used for
    # reinforcement. Both terms are unions of this disk, so the final master
    # has the rolling-disk coverage property without uniformizing wider bands.
    interior = ndi.distance_transform_edt(raw) > radius
    opened = ndi.distance_transform_edt(~interior) <= radius
    reinforced = ndi.distance_transform_edt(~skel) <= radius
    prepared = opened | reinforced
    del skel, interior, opened, reinforced
    before = int(raw.sum())
    added = int(np.count_nonzero(prepared & ~raw))
    removed = int(np.count_nonzero(raw & ~prepared))
    del raw
    art = np.zeros((settings.height, settings.width), dtype=bool)
    x, y = (settings.width - width) // 2, (settings.height - height) // 2
    art[y:y + height, x:x + width] = prepared
    del prepared
    border = boundary_mask(settings)
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'layer_01_bottom.png'
    Image.fromarray(np.where(art | border, 0, 255).astype(np.uint8)).convert('1').save(
        path, dpi=(settings.dpi, settings.dpi))
    # Validate the exported binary image, not just the pre-export arrays.
    with Image.open(path) as exported:
        pixels = np.asarray(exported.convert('L'))
        dpi = exported.info['dpi']
        actual = (pixels == 0) & ~border
    distance = ndi.distance_transform_edt(actual)
    opened_check = ndi.distance_transform_edt(~(distance > radius)) <= radius
    components = int(ndi.label(actual)[1])
    backbone_components = int(ndi.label(distance > 19)[1])
    uncovered = int(np.count_nonzero(actual & ~opened_check))
    symmetry = int(np.count_nonzero(actual != actual[:, ::-1]))
    registration_separate = not bool(np.any(ndi.binary_dilation(actual) & border))
    binary = bool(np.all((pixels == 0) | (pixels == 255)))
    report = {
        'status': 'single-layer visual proof; not an approved manufacturing layer set',
        'source': source.name,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'source_dimensions': source_size,
        'smooth_master_construction': smooth,
        'source_crop': crop,
        'symmetry_method': 'Left half mirrored exactly; no independent drawing',
        'preparation': 'Source topology thinned; radius-24 disk reinforcement plus original broad strokes',
        'source_scaled_black_pixels': before,
        'master_preparation_added_pixels': added,
        'master_preparation_removed_pixels': removed,
        'dimensions': [settings.width, settings.height],
        'dpi': list(dpi),
        'scaling_boundary_external_height_pixels': 6900,
        'scaling_boundary_external_height_inches': 11.5,
        'artwork_connected_components': components,
        'connected_backbones_after_19px_erosion': backbone_components,
        'symmetry_mismatched_pixels': symmetry,
        'minimum_width_uncovered_pixels': uncovered,
        'minimum_width_method': 'Exact radius-24 disk opening plus connected 19px-eroded backbone',
        'binary_colors': binary,
        'registration_separate': registration_separate,
        'registration_exact': bool(np.all(pixels[border] == 0)),
        'stack_containment': 'not run; no upper layers exist',
        'progressive_complexity': 'not run; no upper layers exist',
        'cross_layer_core_consistency': 'not run; no upper layers exist',
        'component_decomposition': 'pending visual approval of master',
    }
    report['single_layer_geometry_passed'] = bool(components == 1 and backbone_components == 1
        and uncovered == 0 and symmetry == 0 and binary and registration_separate
        and report['registration_exact'] and all(abs(d - 600) < .02 for d in dpi))
    (output / 'reference_validation.json').write_text(json.dumps(report, indent=2))
    with Image.open(path) as image:
        preview = image.convert('RGB')
        preview.thumbnail((900, 1020), Image.Resampling.LANCZOS)
        preview.save(output / 'first_layer_preview.png')
    print(json.dumps(report, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--output', required=True)
    parser.add_argument('--smooth', action='store_true', help='Fit organic centerline curves once during master construction')
    args = parser.parse_args()
    prepare_reference(args.source, args.output, smooth=args.smooth)


if __name__ == '__main__':
    main()
