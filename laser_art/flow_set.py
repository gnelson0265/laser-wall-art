"""Schedule complete reference ornaments over balanced removal stages."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from .advance import read_layer
from .engine import boundary_mask, validate
from .finish import green_stack, layer_sheet, structural_guide
from .flow_structure import smooth_support, anchored_centers
from .model import Manufacturing
from .reference import thin
from .reference_layers import disk_union


def group_centers(art, radius):
    distance = ndi.distance_transform_edt(art)
    centers = distance > radius
    if not np.array_equal(disk_union(centers, radius), art):
        raise ValueError('Master is not exactly decomposable into original manufacturing disks.')
    exterior_distance = ndi.distance_transform_edt(ndi.binary_fill_holes(art))
    core_centers = centers & (exterior_distance <= radius+4)
    protected = art & ~ndi.binary_erosion(ndi.binary_fill_holes(art))
    del distance, exterior_distance
    structural, routes = structural_guide(art)
    structural_centers = smooth_support(art, centers, routes, radius)
    structural_centers = anchored_centers(core_centers, structural_centers, radius)
    structural = disk_union(structural_centers, radius)
    h, w = art.shape
    size = (w//5, h//5)
    guide = np.asarray(Image.fromarray(art).resize(size, Image.Resampling.NEAREST))
    skeleton = thin(guide)
    structure_guide = np.asarray(Image.fromarray(structural).resize(size, Image.Resampling.NEAREST))
    core_art = disk_union(core_centers, radius)
    core_guide = np.asarray(Image.fromarray(core_art).resize(size, Image.Resampling.NEAREST))
    support = skeleton & (structure_guide | core_guide)
    optional = skeleton & ~support
    labels, count = ndi.label(optional, structure=np.ones((3, 3)))
    nodes = np.where(optional, labels+2, 2).astype(np.uint16)
    nearest = ndi.distance_transform_edt(~optional, return_distances=False, return_indices=True)
    assigned = nodes[nearest[0], nearest[1]]
    half = assigned[:, :assigned.shape[1]//2]
    assigned = np.concatenate((half, half[:, ::-1]), axis=1)
    owners = np.asarray(Image.fromarray(assigned).resize((w, h), Image.Resampling.NEAREST)).copy()
    owners[~centers] = 0
    owners[structural_centers] = 2
    owners[core_centers] = 1
    thickness = ndi.distance_transform_edt(guide)
    metadata = {1: {'id': 1, 'name': 'Permanent original outline', 'priority': 1e9},
                2: {'id': 2, 'name': 'Main flowing veins', 'priority': 1e6}}
    for label in range(1, count+1):
        component_id = label+2
        if not np.any(owners == component_id):
            continue
        samples = thickness[labels == label]
        metadata[component_id] = {'id': component_id, 'name': f'Mirrored ornament {component_id}',
            'priority': float(samples.mean()), 'guide_nodes': int(len(samples))}
    if np.any(protected & ~core_art):
        raise ValueError('Permanent outline does not cover the protected source contour.')
    return centers, owners, metadata, core_art, routes


def cache_groups(centers, owners, radius):
    cache = {}
    coverage = np.zeros(centers.shape, dtype=np.uint16)
    for group_id in np.unique(owners[centers]):
        ys, xs = np.where(centers & (owners == group_id))
        x0, y0 = max(0, xs.min()-radius-2), max(0, ys.min()-radius-2)
        x1, y1 = min(centers.shape[1], xs.max()+radius+3), min(centers.shape[0], ys.max()+radius+3)
        seeds = centers[y0:y1, x0:x1] & (owners[y0:y1, x0:x1] == group_id)
        mask = disk_union(seeds, radius)
        box = (int(x0), int(y0), int(x1), int(y1))
        cache[int(group_id)] = (box, mask)
        coverage[y0:y1, x0:x1] += mask
    return cache, coverage


def remove_group(coverage, cached):
    (x0, y0, x1, y1), mask = cached
    region = coverage[y0:y1, x0:x1]
    removed = int(np.count_nonzero(mask & (region == 1)))
    if np.any(mask & (region == 0)):
        raise ValueError('Component was already removed.')
    region -= mask
    return removed


def schedule_ornaments(coverage, cache, metadata, total_optional_area, stages):
    groups = sorted((i for i in cache if i > 2), key=lambda i: (metadata[i]['priority'], i))
    if len(groups) < stages:
        raise ValueError('Not enough complete ornaments for distinct removal stages.')
    removed, result = 0, []
    for stage in range(stages):
        target = total_optional_area*(stage+1)/stages
        selected = []
        while groups and (stage == stages-1 or removed < target or not selected):
            # Reserve at least one whole component for every remaining stage.
            if selected and len(groups) <= stages-stage-1:
                break
            group_id = groups.pop(0)
            removed += remove_group(coverage, cache[group_id])
            selected.append(group_id)
        result.append(selected)
    return result


def save_art(art, border, path, dpi=600):
    Image.fromarray(np.where(art | border, 0, 255).astype(np.uint8)).convert('1').save(path, dpi=(dpi, dpi))


def build_set(master_path, output, layers=5):
    if layers < 2:
        raise ValueError('At least two layers are required.')
    output, master_path = Path(output), Path(master_path)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory.')
    settings = Manufacturing()
    border = boundary_mask(settings)
    master, _ = read_layer(master_path, settings)
    art = master & ~border
    centers, owners, metadata, core, routes = group_centers(art, settings.radius)
    cache, coverage = cache_groups(centers, owners, settings.radius)
    if not np.array_equal(coverage > 0, art):
        raise ValueError('Component union must exactly equal the original master.')
    foundation = core.copy()
    if 2 in cache:
        (x0, y0, x1, y1), mask = cache[2]
        foundation[y0:y1, x0:x1] |= mask
    if ndi.label(foundation)[1] != 1:
        raise ValueError('Main structural foundation is disconnected.')
    optional_area = int(np.count_nonzero(art & ~foundation))
    if layers == 2:
        stages = [[i for i in cache if i != 1]]
    else:
        stages = schedule_ornaments(coverage.copy(), cache, metadata, optional_area, layers-2)
        stages.append([2])
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(layers):
        suffix = '_bottom' if index == 0 else '_top' if index == layers-1 else ''
        path = output / f'layer_{index+1:02d}{suffix}.png'
        if index == 0:
            shutil.copyfile(master_path, path)
        else:
            for component_id in stages[index-1]:
                remove_group(coverage, cache[component_id])
            save_art(coverage > 0, border, path)
        paths.append(path)
        print(f'Saved {path.name}', flush=True)
    master_hash = hashlib.sha256(master_path.read_bytes()).hexdigest()
    np.savez_compressed(output/'master_components.npz', centers=centers, owners=owners,
                        radius=np.array(settings.radius), master_sha256=np.array(master_hash))
    (output/'master_components.json').write_text(json.dumps({
        'master_sha256': master_hash, 'components': list(metadata.values()),
        'structural_routes_guide_yx': routes, 'removal_stages': stages,
        'method': 'Original disk centers assigned once to outline, main veins, or complete attached ornament clusters',
        'schedule': 'Fine ornaments first, balanced by exposed material area; main veins last'}, indent=2))
    del cache, coverage, centers, owners, foundation
    components = [[SimpleNamespace(id=str(i)) for i in stage] for stage in stages]
    report = validate(paths, core, settings, components)
    report['master_sha256'] = master_hash
    report['prepared_master_unchanged'] = master_path.read_bytes() == paths[0].read_bytes()
    report['complete_feature_groups'] = len(metadata)
    areas = [row['artwork_pixels'] for row in report['layers']]
    visible = [areas[i]-areas[i+1] if i+1 < layers else areas[i] for i in range(layers)]
    report['exposed_share_percent_bottom_to_top'] = [round(100*n/areas[0], 2) for n in visible]
    (output/'validation_report.json').write_text(json.dumps(report, indent=2))
    if not report['passed']:
        raise ValueError(f'Validation failed; diagnostic layers retained at {output}.')
    palette = green_stack(paths, border, output)
    layer_sheet(paths, output)
    (output/'green_stack_legend.json').write_text(json.dumps(palette, indent=2))
    for path in paths:
        with Image.open(path) as image:
            preview = image.convert('RGB')
            preview.thumbnail((600, 680), Image.Resampling.LANCZOS)
            preview.save(output/f'{path.stem}_preview.png')
    (output/'READ_ME.txt').write_text(
        'FLOWING GINKGO LAYER SET\n\n'
        f'{layers} separate PNGs, bottom (01) through top outline.\n'
        '6400 x 7200 pixels at 600 DPI. Black material; pure white cutouts.\n'
        'Set the separate scaling rectangle to 11.5 inches EXTERNAL height and exclude it from cutting.\n'
        'All layers are subsets of the one prepared master; all mandatory geometric checks passed.\n'
        'Green stack: exact aligned color overlays, dark bottom through pale top; visualization only.\n'
        'All layers require a test cut for material and kerf.\n')
    with zipfile.ZipFile(output/f'ginkgo_flow_{layers}_layers.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            if path.is_file() and path.suffix != '.zip':
                archive.write(path, path.name)
    print(json.dumps({'passed': report['passed'], 'layer_areas': areas,
                      'exposed_share_percent_bottom_to_top': report['exposed_share_percent_bottom_to_top'],
                      'component_groups': len(metadata)}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('master')
    parser.add_argument('--output', required=True)
    parser.add_argument('--layers', type=int, default=5)
    args = parser.parse_args()
    build_set(args.master, args.output, args.layers)


if __name__ == '__main__':
    main()
