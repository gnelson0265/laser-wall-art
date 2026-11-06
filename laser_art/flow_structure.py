"""Choose smooth structural components from existing master disk centers only."""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from .smooth import raster_smooth_centerlines


def smooth_support(art, centers, routes, radius, factor=5):
    h, w = art.shape
    shape = (h//factor, w//factor)
    chosen = np.zeros(shape, dtype=bool)
    widths = np.zeros(shape, dtype=np.float32)
    distance = ndi.distance_transform_edt(art)
    for path in routes:
        ys, xs = np.asarray(path).T
        samples = distance[np.minimum(h-1, ys*factor+factor//2),
                           np.minimum(w-1, xs*factor+factor//2)]
        profile = ndi.gaussian_filter1d(ndi.median_filter(samples, size=21), sigma=5)
        chosen[ys, xs] = True
        np.maximum.at(widths, (ys, xs), np.maximum(radius+5, profile*.95))
    del distance
    nearest = ndi.distance_transform_edt(~chosen, return_distances=False, return_indices=True)
    field = widths[nearest[0], nearest[1]]
    half = field[:, :shape[1]//2]
    field = np.concatenate((half, half[:, ::-1]), axis=1)
    field = np.asarray(Image.fromarray(field).resize((w, h), Image.Resampling.BILINEAR))
    curve = raster_smooth_centerlines(chosen, (w, h), 0)
    curve_distance = ndi.distance_transform_edt(~curve)
    result = centers & (curve_distance <= np.maximum(5, field-radius))
    half = result[:, :w//2]
    return np.concatenate((half, half[:, ::-1]), axis=1)


def anchored_centers(core_centers, structural_centers, radius):
    """Drop optional structural tips with an undersized neck to the outline.

    Dropped centers remain available as ornament components in the master.
    They are never moved, widened, or introduced into an upper layer.
    """
    from .reference_layers import disk_union
    current = structural_centers.copy()
    for _ in range(8):
        foundation = disk_union(core_centers | current, radius)
        backbone = ndi.distance_transform_edt(foundation) > 19
        labels, count = ndi.label(backbone)
        roots = np.unique(labels[core_centers])
        if len(roots) != 1 or roots[0] == 0:
            raise ValueError('Permanent outline has disconnected material-width backbones.')
        if count == 1:
            return current
        kept = current & (labels == roots[0])
        if np.array_equal(kept, current):
            raise ValueError('Cannot anchor structural components at manufacturing width.')
        current = kept
    raise ValueError('Structural width anchoring failed to converge.')
