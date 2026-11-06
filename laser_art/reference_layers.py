"""Decompose a reference master into immutable disk-union feature groups.

The master is exactly a union of inscribed radius-24 disks. Assign each disk
center once to a traced terminal scroll or the retained structure. An upper
layer removes whole groups of those original disks; no new geometry is drawn.
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
from .reference import thin


def neighbors(skeleton, point):
    y, x = point
    height, width = skeleton.shape
    result = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if not (dy or dx):
                continue
            yy, xx = y + dy, x + dx
            if not (0 <= yy < height and 0 <= xx < width) or not skeleton[yy, xx]:
                continue
            # Diagonal shortcuts at a raster corner create artificial junctions.
            if dy and dx and (skeleton[y, xx] or skeleton[yy, x]):
                continue
            result.append((yy, xx))
    return result


def terminal_paths(skeleton):
    paths = []
    height, width = skeleton.shape
    for y, x in np.argwhere(skeleton):
        start = (int(y), int(x))
        if x >= width // 2 or len(neighbors(skeleton, start)) != 1:
            continue
        path, previous, here = [start], None, start
        while True:
            options = [p for p in neighbors(skeleton, here) if p != previous]
            if len(options) != 1:
                break
            previous, here = here, options[0]
            path.append(here)
        paths.append(path)
    return paths


def disk_union(centers, radius):
    return ndi.distance_transform_edt(~centers) <= radius


def create_second_layer(master_path, output, fraction=.65):
    master_path, output = Path(master_path), Path(output)
    if not 0 < fraction <= 1:
        raise ValueError('Removal fraction must be greater than zero and at most one.')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory.')
    settings = Manufacturing()
    radius = settings.radius
    border = boundary_mask(settings)
    with Image.open(master_path) as image:
        if image.size != (settings.width, settings.height):
            raise ValueError('Master dimensions differ from the manufacturing contract.')
        dpi = image.info.get('dpi')
        original = np.asarray(image.convert('L'))
    if not dpi or any(abs(d - 600) > .02 for d in dpi):
        raise ValueError('Master must have 600 DPI metadata.')
    if not np.all((original == 0) | (original == 255)):
        raise ValueError('Master must be binary black and white.')
    black = original == 0
    if not np.all(black[border]):
        raise ValueError('Master registration boundary is incomplete.')
    art = black & ~border
    if np.any(art != art[:, ::-1]):
        raise ValueError('Master must be exactly symmetric.')
    centers = ndi.distance_transform_edt(art) > radius
    if not np.array_equal(disk_union(centers, radius), art):
        raise ValueError('Master is not exactly decomposable using the fixed manufacturing disk.')
    # Skeleton geometry guides grouping only; it never draws output pixels.
    factor = 5
    guide_size = (settings.width // factor, settings.height // factor)
    guide = np.asarray(Image.fromarray(art).resize(guide_size, Image.Resampling.NEAREST))
    skeleton = thin(guide)
    paths = terminal_paths(skeleton)
    thickness = ndi.distance_transform_edt(guide)
    skeleton_groups = np.zeros(guide.shape, dtype=np.uint16)
    groups = []
    for path in paths:
        # Skip pixel-scale spurs and the long petiole terminal. Both remain in
        # the retained structure, as do cycles and nonterminal branch segments.
        if len(path) < 24 or path[0][0] > guide.shape[0] * .70:
            continue
        group_id = len(groups) + 1
        for point in path[:-1]:
            skeleton_groups[point] = group_id
        ys, xs = np.array(path[:-1]).T
        groups.append({'id': group_id, 'name': f'terminal_scroll_pair_{group_id:02d}',
                       'guide_path_yx': path, 'guide_length': len(path),
                       'mean_half_width_guide_pixels': float(thickness[ys, xs].mean())})
    if not groups:
        raise ValueError('No removable terminal scrolls were identified.')
    nearest = ndi.distance_transform_edt(~skeleton, return_distances=False, return_indices=True)
    assigned = skeleton_groups[nearest[0], nearest[1]]
    half = assigned[:, :assigned.shape[1] // 2]
    assigned = np.concatenate((half, half[:, ::-1]), axis=1)
    owners = np.asarray(Image.fromarray(assigned).resize(
        (settings.width, settings.height), Image.Resampling.NEAREST)).copy()
    # Protect the actual master core. Any disk that could cover its two-radius
    # exterior band stays in the retained group, preserving the full silhouette.
    solid = ndi.binary_fill_holes(art)
    exterior_distance = ndi.distance_transform_edt(solid)
    core = art & (exterior_distance <= 2 * radius)
    owners[(~centers) | (exterior_distance <= 3 * radius)] = 0
    del exterior_distance, solid, nearest, assigned
    counts = np.bincount(owners[centers].ravel())
    candidates = []
    for group in groups:
        count = int(counts[group['id']]) if group['id'] < len(counts) else 0
        group['master_disk_centers'] = count
        if count >= 500:
            candidates.append(group)
    # Fine terminal curls are removed first, in complete mirrored pairs.
    candidates.sort(key=lambda g: (g['mean_half_width_guide_pixels'], g['guide_length'], g['id']))
    remove_count = max(1, round(len(candidates) * fraction))
    removed = [g['id'] for g in candidates[:remove_count]]
    keep_centers = centers & ~np.isin(owners, removed)
    upper_art = disk_union(keep_centers, radius)
    # This is mathematically a subset; assert against the exact exported master.
    introduced = int(np.count_nonzero(upper_art & ~art))
    lost_core = int(np.count_nonzero(core & ~upper_art))
    removed_pixels = int(np.count_nonzero(art & ~upper_art))
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'layer_02.png'
    Image.fromarray(np.where(upper_art | border, 0, 255).astype(np.uint8)).convert('1').save(
        path, dpi=(600, 600))
    with Image.open(path) as image:
        exported = np.asarray(image.convert('L'))
        actual = (exported == 0) & ~border
        actual_dpi = image.info.get('dpi')
    distance = ndi.distance_transform_edt(actual)
    uncovered = int(np.count_nonzero(actual & ~disk_union(distance > radius, radius)))
    components = int(ndi.label(actual)[1])
    backbones = int(ndi.label(distance > 19)[1])
    symmetry = int(np.count_nonzero(actual != actual[:, ::-1]))
    outside = int(np.count_nonzero((exported == 0) & ~black))
    report = {
        'master_sha256': hashlib.sha256(master_path.read_bytes()).hexdigest(),
        'master_file': master_path.name,
        'layer_file': path.name,
        'method': 'Remove complete mirrored terminal-scroll disk groups from a single exact master decomposition',
        'master_decomposition_exact': True,
        'disk_radius_pixels': radius,
        'available_terminal_scroll_pairs': len(candidates),
        'removed_terminal_scroll_pairs': removed,
        'component_manifest': 'master_components.json',
        'decomposition_file': 'master_component_centers.npz',
        'introduced_black_pixels': outside,
        'missing_core_pixels': lost_core,
        'symmetry_mismatched_pixels': symmetry,
        'artwork_connected_components': components,
        'connected_backbones_after_19px_erosion': backbones,
        'minimum_width_uncovered_pixels': uncovered,
        'master_artwork_pixels': int(art.sum()),
        'layer_2_artwork_pixels': int(actual.sum()),
        'removed_artwork_pixels': removed_pixels,
        'removed_percent': round(100 * removed_pixels / int(art.sum()), 2),
        'dimensions': [settings.width, settings.height],
        'dpi': actual_dpi,
        'registration_exact': bool(np.all(exported[border] == 0)),
        'registration_separate': not bool(np.any(ndi.binary_dilation(actual) & border)),
        'binary_colors': bool(np.all((exported == 0) | (exported == 255))),
        'later_layers': 'not generated',
    }
    report['passed'] = bool(introduced == outside == lost_core == symmetry == uncovered == 0
        and components == backbones == 1 and removed_pixels >= 1444
        and report['registration_exact'] and report['registration_separate']
        and report['binary_colors'] and np.array_equal(upper_art, actual)
        and actual_dpi and all(abs(d - 600) < .02 for d in actual_dpi))
    (output / 'layer_02_validation.json').write_text(json.dumps(report, indent=2))
    # Persist group ownership once. Every surviving group keeps exactly the
    # same disk centers and radius for all future layer operations.
    np.savez_compressed(output / 'master_component_centers.npz', centers=centers, owners=owners,
                        radius=np.array(radius), master_sha256=np.array(report['master_sha256']))
    (output / 'master_components.json').write_text(json.dumps({
        'master_sha256': report['master_sha256'], 'retained_group': 0,
        'groups': groups, 'removed_in_layer_2': removed,
        'core_definition': 'Master artwork within 48px of filled silhouette exterior; protected by original disks',
        'guide_scale_factor': factor}, indent=2))
    if not report['passed']:
        raise ValueError(f'Layer 2 failed validation: {output / "layer_02_validation.json"}')
    with Image.open(path) as image:
        preview = image.convert('RGB')
        preview.thumbnail((900, 1020), Image.Resampling.LANCZOS)
        preview.save(output / 'layer_02_preview.png')
    # Highlight exactly the removed master pixels, without changing either layer.
    difference = np.full((*art.shape, 3), 255, dtype=np.uint8)
    difference[art] = (195, 195, 195)
    difference[art & ~actual] = (196, 40, 40)
    preview = Image.fromarray(difference)
    preview.thumbnail((900, 1020), Image.Resampling.LANCZOS)
    preview.save(output / 'removed_features_preview.png')
    print(json.dumps(report, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('master')
    parser.add_argument('--output', required=True)
    parser.add_argument('--fraction', type=float, default=.65)
    args = parser.parse_args()
    create_second_layer(args.master, args.output, args.fraction)


if __name__ == '__main__':
    main()
