"""Finish an approved reference sequence with a structural layer and outline.

Refine ownership of the original retained disk group. No disk center or radius
changes. All output layers remain unions of subsets of those original disks.
"""
import argparse
import colorsys
import hashlib
import json
import math
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .advance import read_layer
from .engine import boundary_mask, validate
from .model import Manufacturing
from .reference import thin
from .reference_layers import disk_union, neighbors

GREENS = ['#123d24', '#216b3a', '#399750', '#6bbc70', '#a7dca0']


def structural_guide(art, factor=5):
    height, width = art.shape
    guide = np.asarray(Image.fromarray(art).resize((width // factor, height // factor),
                                                   Image.Resampling.NEAREST))
    skeleton = thin(guide)
    points = np.argwhere(skeleton)
    node_ids = np.full(skeleton.shape, -1, dtype=np.int32)
    node_ids[points[:, 0], points[:, 1]] = np.arange(len(points))
    thickness = ndi.distance_transform_edt(guide)
    rows, columns, weights = [], [], []
    for i, (y, x) in enumerate(points):
        for yy, xx in neighbors(skeleton, (y, x)):
            rows.append(i)
            columns.append(int(node_ids[yy, xx]))
            # Favor the broad natural veins over small ornamental diversions.
            weights.append(math.hypot(yy-y, xx-x) /
                           (1 + min(thickness[y, x], thickness[yy, xx]) / 3))
    graph = csr_matrix((weights, (rows, columns)), shape=(len(points), len(points)))
    h, w = guide.shape
    root = int(np.argmin((points[:, 0] - .70*h)**2 + (points[:, 1] - .50*w)**2))
    distances, predecessors = dijkstra(graph, indices=root, return_predecessors=True)
    # Use the unchanged master bounding box to locate fan-edge anchor regions.
    # Anchor points select existing paths; they never specify new line geometry.
    y, x = np.where(guide)
    y0, x0, ah, aw = y.min(), x.min(), y.max()-y.min()+1, x.max()-x.min()+1
    targets = [(0.04, .45), (.06, .29), (.18, .16), (.30, .06), (.42, .02), (.48, .10)]
    chosen = np.zeros_like(skeleton)
    traced = []
    for fx, fy in targets:
        target = np.array([y0 + fy*ah, x0 + fx*aw])
        order = np.argsort(np.sum((points-target)**2, axis=1))
        end = next((int(i) for i in order if np.isfinite(distances[i])), None)
        if end is None:
            raise ValueError('No connected structural route reaches a fan anchor.')
        path, i = [], end
        while i != root:
            yy, xx = points[i]
            chosen[yy, xx] = True
            path.append([int(yy), int(xx)])
            i = int(predecessors[i])
            if i < 0:
                raise ValueError('Incomplete structural path.')
        chosen[tuple(points[root])] = True
        path.append([int(v) for v in points[root]])
        traced.append(path)
    nearest = ndi.distance_transform_edt(~skeleton, return_distances=False, return_indices=True)
    assigned = chosen[nearest[0], nearest[1]]
    half = assigned[:, :w//2]
    assigned = np.concatenate((half, half[:, ::-1]), axis=1)
    full = np.asarray(Image.fromarray(assigned).resize((width, height), Image.Resampling.NEAREST))
    return full, traced


def rgb_color(value):
    return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))


def green_stack(paths, border, output):
    shape = border.shape
    palette = GREENS if len(paths) == 5 else [
        '#%02x%02x%02x' % tuple(round(v*255) for v in colorsys.hls_to_rgb(.36, lightness, .5))
        for lightness in np.linspace(.17, .76, len(paths))]
    stacked = np.full((*shape, 3), 255, dtype=np.uint8)
    areas = []
    for path, color in zip(paths, palette):
        with Image.open(path) as image:
            art = (np.asarray(image.convert('L')) == 0) & ~border
        stacked[art] = rgb_color(color)
        areas.append(art)
    Image.fromarray(stacked).save(output / 'stacked_green.png', dpi=(600, 600))
    preview = Image.fromarray(stacked)
    preview.thumbnail((900, 1020), Image.Resampling.LANCZOS)
    preview.save(output / 'stacked_green_preview.png')
    # Check each visible band uses the shade of the physically highest ply.
    visible_counts = []
    for i, art in enumerate(areas):
        visible = art if i == len(areas)-1 else art & ~areas[i+1]
        count = int(visible.sum())
        if count == 0 or not np.all(stacked[visible] == rgb_color(palette[i])):
            raise ValueError('Green stack does not faithfully depict layer ordering.')
        visible_counts.append(count)
    return {'view': 'Aligned top view; layer 1 bottom, layer 5 top; registration excluded',
            'colors_bottom_to_top': palette, 'visible_pixels_per_layer': visible_counts,
            'all_five_shades_visible': True,
            'rendering': 'Exact opaque green layer overlays; no simulated kerf or material thickness'}


def layer_sheet(paths, output):
    sheet = Image.new('RGB', (440*len(paths), 540), '#f1eee7')
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(paths):
        with Image.open(path) as image:
            preview = image.convert('RGB')
            preview.thumbnail((420, 480), Image.Resampling.LANCZOS)
        sheet.paste(preview, (i * 440 + 10, 40))
        suffix = 'bottom' if i == 0 else 'top' if i == len(paths)-1 else 'middle'
        draw.text((i * 440 + 15, 15), f'Layer {i+1}: {suffix}', fill='#243d29')
    sheet.save(Path(output) / 'all_layers_preview.png')


def finish(master_path, second_path, third_path, component_dir, third_report_path, output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory.')
    settings = Manufacturing()
    border = boundary_mask(settings)
    master_path, second_path, third_path = map(Path, (master_path, second_path, third_path))
    third_report = json.loads(Path(third_report_path).read_text())
    master_hash = hashlib.sha256(master_path.read_bytes()).hexdigest()
    if not third_report.get('passed') or third_report['master_sha256'] != master_hash:
        raise ValueError('Layer 3 must pass and belong to this master.')
    master, _ = read_layer(master_path, settings)
    third, _ = read_layer(third_path, settings)
    art, third_art = master & ~border, third & ~border
    with np.load(Path(component_dir) / 'master_component_centers.npz', allow_pickle=False) as data:
        centers, owners = data['centers'], data['owners']
        if str(data['master_sha256']) != master_hash or int(data['radius']) != settings.radius:
            raise ValueError('Disk decomposition belongs to a different master.')
    removed = third_report['cumulative_removed_terminal_scroll_pairs']
    retained = centers & ~np.isin(owners, removed)
    if not np.array_equal(disk_union(centers, settings.radius), art):
        raise ValueError('Original disk decomposition does not reconstruct master exactly.')
    if not np.array_equal(disk_union(retained, settings.radius), third_art):
        raise ValueError('Layer 3 differs from saved original-component state.')
    # The already protected master exterior band defines the permanent outline.
    solid = ndi.binary_fill_holes(art)
    distance = ndi.distance_transform_edt(solid)
    core_centers = retained & (distance <= 3 * settings.radius)
    protected_pixels = art & (distance <= 2 * settings.radius)
    del solid, distance
    guide, traced = structural_guide(third_art)
    # Refine the retained component into outline, major structure, decoration.
    # All original ownership outside this component is left unchanged.
    refined = owners.copy()
    refined[retained] = 22
    refined[retained & guide] = 21
    refined[core_centers] = 20
    fourth = disk_union(centers & np.isin(refined, (20, 21)), settings.radius)
    fifth = disk_union(centers & (refined == 20), settings.radius)
    if np.any(protected_pixels & ~fifth):
        raise ValueError('Top outline fails to preserve the original protected core.')
    if np.any(fourth & ~third_art) or np.any(fifth & ~fourth):
        raise ValueError('Component selection introduced material.')
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / name for name in ('layer_01_bottom.png', 'layer_02.png', 'layer_03.png',
                                       'layer_04.png', 'layer_05_top.png')]
    for source, destination in zip((master_path, second_path, third_path), paths[:3]):
        shutil.copyfile(source, destination)
    for mask, path in zip((fourth, fifth), paths[3:]):
        Image.fromarray(np.where(mask | border, 0, 255).astype(np.uint8)).convert('1').save(
            path, dpi=(600, 600))
    np.savez_compressed(output / 'master_final_components.npz', centers=centers, owners=refined,
                        radius=np.array(settings.radius), master_sha256=np.array(master_hash))
    del owners, centers, retained, guide, refined
    stage_ids = [third_report['previously_removed_terminal_scroll_pairs'],
                 third_report['newly_removed_terminal_scroll_pairs'], [22], [21]]
    stages = [[SimpleNamespace(id=str(i)) for i in ids] for ids in stage_ids]
    report = validate(paths, fifth, settings, stages)
    report['master_sha256'] = master_hash
    report['previously_approved_layers_unchanged'] = all(
        hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(destination.read_bytes()).digest()
        for source, destination in zip((master_path, second_path, third_path), paths[:3]))
    report['original_protected_core_preserved'] = not bool(np.any(protected_pixels & ~fifth))
    (output / 'validation_report.json').write_text(json.dumps(report, indent=2))
    if not report['passed'] or not report['previously_approved_layers_unchanged']:
        raise ValueError(f'Full-set validation failed; see {output / "validation_report.json"}')
    palette = green_stack(paths, border, output)
    layer_sheet(paths, output)
    (output / 'green_stack_legend.json').write_text(json.dumps(palette, indent=2))
    for path in paths:
        with Image.open(path) as image:
            preview = image.convert('RGB')
            preview.thumbnail((600, 680), Image.Resampling.LANCZOS)
            preview.save(output / f'{path.stem}_preview.png')
    manifest = {'master_sha256': master_hash,
                'source_component_manifest': 'layer-2 master_components.json (unchanged)',
                'refinement': {'20': 'Permanent original outline disks',
                               '21': 'Original disk groups along major vein routes',
                               '22': 'Remaining original interior ornament disks'},
                'structural_routes_guide_yx': traced,
                'core_definition': 'Original protected silhouette band, no reconstructed outline',
                'layer_4_retained_groups': [20, 21], 'layer_5_retained_groups': [20],
                'guide_scale_factor': 5}
    (output / 'final_components.json').write_text(json.dumps(manifest, indent=2))
    (output / 'READ_ME.txt').write_text(
        'FIVE-LAYER GINKGO SET\n\n'
        'layer_01_bottom.png is the most detailed bottom ply. Stack 02, 03, 04, then 05_top.\n'
        'All manufacturing layers are black material on white; identical 6400 x 7200 px at 600 DPI.\n'
        'Scale the separate registration rectangle to 11.5 inches EXTERNAL height; exclude it from cutting.\n'
        'The top is only the original outline. All five layers passed pixel, width, and connectivity checks.\n'
        'stacked_green.png is an aligned top-view color illustration, not a cutting file.\n'
        'Colors from bottom to top: ' + ', '.join(GREENS) + '.\n'
        'Test cut for kerf, strength, and assembly. No physical material simulation was performed.\n')
    with zipfile.ZipFile(output / 'ginkgo_five_layers_green.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            if path.is_file() and path.suffix != '.zip':
                archive.write(path, path.name)
    with zipfile.ZipFile(output / 'ginkgo_five_layers_green.zip') as archive:
        if archive.testzip() is not None:
            raise ValueError('Bundle integrity check failed.')
    print(json.dumps({'passed': report['passed'], 'layers': [
        {'file': r['file'], 'pixels': r['artwork_pixels'], 'passed': r['passed']}
        for r in report['layers']], 'green_stack': palette,
        'bundle': str(output / 'ginkgo_five_layers_green.zip')}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', required=True)
    parser.add_argument('--second', required=True)
    parser.add_argument('--third', required=True)
    parser.add_argument('--components', required=True)
    parser.add_argument('--third-report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    finish(args.master, args.second, args.third, args.components, args.third_report, args.output)


if __name__ == '__main__':
    main()
