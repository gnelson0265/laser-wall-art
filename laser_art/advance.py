"""Advance a reference layer using only its saved original component masks."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from .engine import boundary_mask
from .model import Manufacturing
from .reference_layers import disk_union


def removal_plan(manifest, previous_report, requested=None):
    eligible = {g['id'] for g in manifest['groups'] if g['master_disk_centers'] >= 500}
    old = set(previous_report.get('cumulative_removed_terminal_scroll_pairs',
                                 previous_report.get('removed_terminal_scroll_pairs', [])))
    if not old <= eligible:
        raise ValueError('Previous removal state refers to unknown components.')
    new = eligible - old if requested is None else set(requested)
    if not new or not new <= eligible - old:
        raise ValueError('Select nonempty, still-retained terminal component groups.')
    return sorted(old), sorted(new), sorted(old | new)


def read_layer(path, settings):
    with Image.open(path) as image:
        pixels = np.asarray(image.convert('L'))
        dpi = image.info.get('dpi')
        if image.size != (settings.width, settings.height):
            raise ValueError('Layer dimensions differ from the master contract.')
    if not dpi or any(abs(d - settings.dpi) > .02 for d in dpi):
        raise ValueError('Layer must retain 600 DPI metadata.')
    if not np.all((pixels == 0) | (pixels == 255)):
        raise ValueError('Layer must contain only pure black and white.')
    return pixels == 0, dpi


def advance_layer(master_path, component_directory, previous_path, previous_report_path,
                  output, layer_number=3, remove_ids=None):
    if layer_number < 3:
        raise ValueError('Use the original reference layer generator for layer 2.')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory.')
    master_path, previous_path = Path(master_path), Path(previous_path)
    directory = Path(component_directory)
    manifest_path = directory / 'master_components.json'
    manifest = json.loads(manifest_path.read_text())
    previous_report = json.loads(Path(previous_report_path).read_text())
    master_hash = hashlib.sha256(master_path.read_bytes()).hexdigest()
    if not previous_report.get('passed'):
        raise ValueError('Previous layer has not passed its required checks.')
    if any(source['master_sha256'] != master_hash for source in (manifest, previous_report)):
        raise ValueError('Component data or prior report belongs to a different master.')
    if previous_report['layer_file'] != previous_path.name:
        raise ValueError('Previous report names a different layer.')
    old, new, cumulative = removal_plan(manifest, previous_report, remove_ids)
    settings = Manufacturing()
    border = boundary_mask(settings)
    master, _ = read_layer(master_path, settings)
    previous, _ = read_layer(previous_path, settings)
    if not np.all(master[border]) or not np.all(previous[border]):
        raise ValueError('Registration boundary is incomplete.')
    component_path = directory / 'master_component_centers.npz'
    with np.load(component_path, allow_pickle=False) as data:
        centers = data['centers']
        owners = data['owners']
        radius = int(data['radius'])
        if str(data['master_sha256']) != master_hash or radius != settings.radius:
            raise ValueError('Saved disk geometry belongs to another master or radius.')
    if centers.shape != master.shape or owners.shape != master.shape:
        raise ValueError('Component grid dimensions differ from the master.')
    master_art = master & ~border
    if not np.array_equal(disk_union(centers, radius), master_art):
        raise ValueError('Saved decomposition does not exactly reconstruct the original master.')
    previous_art = previous & ~border
    expected_previous = disk_union(centers & ~np.isin(owners, old), radius)
    if not np.array_equal(expected_previous, previous_art):
        raise ValueError('Previous PNG differs from its saved component removal state.')
    del expected_previous
    # Original disk centers, group ownership, and radii are never changed.
    upper = disk_union(centers & ~np.isin(owners, cumulative), radius)
    solid = ndi.binary_fill_holes(master_art)
    core = master_art & (ndi.distance_transform_edt(solid) <= 2 * radius)
    del solid
    output.mkdir(parents=True, exist_ok=True)
    name = f'layer_{layer_number:02d}'
    path = output / f'{name}.png'
    Image.fromarray(np.where(upper | border, 0, 255).astype(np.uint8)).convert('1').save(
        path, dpi=(settings.dpi, settings.dpi))
    exported, dpi = read_layer(path, settings)
    actual = exported & ~border
    distance = ndi.distance_transform_edt(actual)
    uncovered = int(np.count_nonzero(actual & ~disk_union(distance > radius, radius)))
    count = int(ndi.label(actual)[1])
    backbones = int(ndi.label(distance > 19)[1])
    removed_pixels = int(np.count_nonzero(previous_art & ~actual))
    report = {
        'master_sha256': master_hash,
        'master_file': master_path.name,
        'previous_file': previous_path.name,
        'previous_sha256': hashlib.sha256(previous_path.read_bytes()).hexdigest(),
        'layer_file': path.name,
        'layer_number': layer_number,
        'method': 'Remove additional complete mirrored groups from the unchanged original master decomposition',
        'master_decomposition_exact': True,
        'previous_component_state_exact': True,
        'component_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'component_centers_sha256': hashlib.sha256(component_path.read_bytes()).hexdigest(),
        'disk_radius_pixels': radius,
        'previously_removed_terminal_scroll_pairs': old,
        'newly_removed_terminal_scroll_pairs': new,
        'cumulative_removed_terminal_scroll_pairs': cumulative,
        'introduced_black_pixels': int(np.count_nonzero(exported & ~previous)),
        'introduced_pixels_relative_to_master': int(np.count_nonzero(exported & ~master)),
        'missing_core_pixels': int(np.count_nonzero(core & ~actual)),
        'symmetry_mismatched_pixels': int(np.count_nonzero(exported != exported[:, ::-1])),
        'artwork_connected_components': count,
        'connected_backbones_after_19px_erosion': backbones,
        'minimum_width_uncovered_pixels': uncovered,
        'previous_artwork_pixels': int(previous_art.sum()),
        'artwork_pixels': int(actual.sum()),
        'removed_artwork_pixels': removed_pixels,
        'removed_percent_of_previous': round(100 * removed_pixels / int(previous_art.sum()), 2),
        'dimensions': [settings.width, settings.height],
        'dpi': list(dpi),
        'scaling_boundary_external_height_pixels': 6900,
        'scaling_boundary_external_height_inches': 11.5,
        'registration_exact': bool(np.array_equal(exported & border, border)),
        'registration_separate': not bool(np.any(ndi.binary_dilation(actual) & border)),
        'later_layers': 'not generated',
    }
    report['passed'] = bool(report['introduced_black_pixels'] == 0
        and report['introduced_pixels_relative_to_master'] == 0
        and report['missing_core_pixels'] == report['symmetry_mismatched_pixels'] == uncovered == 0
        and count == backbones == 1 and removed_pixels >= 1444
        and report['registration_exact'] and report['registration_separate']
        and np.array_equal(actual, upper))
    (output / f'{name}_validation.json').write_text(json.dumps(report, indent=2))
    if not report['passed']:
        raise ValueError(f'Layer failed required checks; see {name}_validation.json.')
    with Image.open(path) as image:
        preview = image.convert('RGB')
        preview.thumbnail((900, 1020), Image.Resampling.LANCZOS)
        preview.save(output / f'{name}_preview.png')
    # Preview downsampling affects only visualization, never manufacturing masks.
    preview_size = (900, 1013)
    base = np.asarray(Image.fromarray(previous_art).resize(preview_size, Image.Resampling.NEAREST))
    removed = np.asarray(Image.fromarray(previous_art & ~actual).resize(preview_size, Image.Resampling.NEAREST))
    difference = np.full((*base.shape, 3), 255, dtype=np.uint8)
    difference[base] = (195, 195, 195)
    difference[removed] = (196, 40, 40)
    Image.fromarray(difference).save(output / 'removed_features_preview.png')
    print(json.dumps(report, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', required=True)
    parser.add_argument('--components', required=True)
    parser.add_argument('--previous', required=True)
    parser.add_argument('--previous-report', required=True)
    parser.add_argument('--layer', type=int, default=3)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    advance_layer(args.master, args.components, args.previous, args.previous_report,
                  args.output, args.layer)


if __name__ == '__main__':
    main()
