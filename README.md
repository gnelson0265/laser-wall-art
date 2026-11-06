# Layerleaf — Layered Laser Art Studio

A Python CLI for deterministic, connected, symmetric laser art. Design once;
remove complete component groups progressively; never redraw surviving geometry.
The first subject renderer is a **ginkgo leaf** (also accepts “gingko”). The
layer engine, validation, exports, and saved-master format are subject-independent.
Other subjects need a dedicated renderer. The website supports the refined
ginkgo preset and black-and-white ginkgo references; arbitrary subject generation
is not offered as a one-click feature.


## Website — free GitHub Pages hosting

The `docs/` website runs the real Python generator in a Web Worker using Pyodide,
NumPy, SciPy, and Pillow. A complete 600-DPI, five-layer export has been verified
in Chromium. No generation server, API key, account, or paid hosting is required.
Runtime libraries load from the pinned public jsDelivr Pyodide CDN; reference
images and generated files stay in the visitor's browser. Desktop Chrome or Edge
is recommended; high-resolution processing needs substantial local memory.

The guided flow asks for the subject, then 2–12 layers, then a sample or uploaded
reference and tip style. Users review the actual frozen master before approving
export. The engine verifies that layer 1 matches that reviewed PNG byte for byte.
Results include individual PNGs, a green stack, cutting checks, and a ZIP.
The site currently supports **ginkgo leaves**. Other subject layouts still need
dedicated authoring work; the UI rejects unsupported subjects explicitly.

### Run the website locally

```sh
python3 scripts/build_site.py
python3 -m http.server 8000 --directory docs
```

Open the local server in a desktop browser. First use downloads the runtime
libraries; generation may take several minutes. Save the ZIP before closing the
tab. The website has no persistent server-side file library.

### Publish on GitHub Pages

The prepared `website` branch can be hosted directly:

1. Open repository **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select branch **website**, folder **/docs**, and click **Save**.
4. GitHub provides the live URL after its deployment finishes, normally
   `https://gnelson0265.github.io/laser-wall-art/` for this repository.

No backend service is required. Pages is free for public repositories; private
repository eligibility depends on the account's GitHub plan. Enabling Pages
requires repository admin access. This preparation does not enable Pages or
establish a live deployment.

The website build is committed in `docs/`. After changing the Python engine, run
`python3 scripts/build_site.py` before updating that branch. If you prefer an
Actions deployment, copy `deployment/github-pages-workflow.yml` into
`.github/workflows/pages.yml`, select **GitHub Actions** as the Pages source,
and run **Publish Layerleaf website** manually. The optional test workflow is
also provided under `deployment/`.

### Browser verification

To repeat the UI checks, install the optional test dependency with
`python3 -m pip install '.[browser-test]'`, install Chromium with
`python3 -m playwright install chromium`, and run
`python3 scripts/test_browser.py --url http://127.0.0.1:8000/` while the local
server is running. Add `--generate` for a real full-resolution export.

The studio's Python API validates uploads and options, freezes master geometry,
and rejects export if the reviewed master changes. Unit tests exercise the full
prepare/review/export handoff. Browser checks also cover the actual 600-DPI
five-layer pipeline, generated ZIP download, validation views, unsupported
subjects, invalid layer counts, and desktop/mobile layouts.

## Run

Python 3.11+ is required. From this checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m laser_art.cli
```

The interactive flow asks for a subject, then a layer count of at least two,
before constructing artwork. Noninteractive usage:

```sh
python3 -m laser_art.cli --subject 'ginkgo leaf' --layers 5 --output outputs/ginkgo-5
python3 -m laser_art.cli --master outputs/ginkgo-5/master.json --layers 3 --output outputs/ginkgo-3
python3 -m unittest discover -s tests -v
```

Use an empty output directory; existing designs are never overwritten. This master
has 55 removable mirrored groups and supports up to 56 scheduled layers. The
actual geometric validation must still pass: layers with no meaningful exposed
area removal are rejected rather than silently exported as accepted manufacturing
sets. Generation and full-resolution validation take a few minutes and may use
several GB of RAM. No credentials, cloud services, or image-generation APIs are
required.

## Outputs

- `layer_01_bottom.png` through `layer_05_top.png` (count adapts to the request).
- `layers_preview.png`, showing individual layers.
- `stacking_preview.png`, an illustrative exploded stack of the actual masks.
- `master.json`, containing all immutable component paths and removal priorities.
- `validation_report.json`, containing measured results for every layer.
- `manufacturing_bundle.zip`, created only when every mandatory check passes.

The manufacturing PNGs contain only pure black material on pure white. They are
6400 × 7200 pixels, with 600 DPI metadata. PNG stores resolution in integer pixels
per metre, so readers may display 599.9988 DPI. The separate registration rectangle
occupies inclusive coordinates `(150,150)` to `(6249,7049)`: its **external height
is exactly 6900 pixels**, representing 11.5 inches at the intended 600 DPI. Scale
to this rectangle's external height in your laser software. It is a measurement
reference; exclude it from the artwork cut structure. Previews have labels and
colors and are **not manufacturing files**.

## Geometry and validation

Every stroke is rasterized once as a union of radius-24-pixel disks (49 pixels
across, exceeding the required 38-pixel minimum). Each half is mirrored by an exact
array flip. Component masks contribute to an integer coverage buffer; removal
subtracts their cached contributions, preserving overlaps and every surviving
pixel. The top layer contains only the original connected outline and petiole.

Validation reopens the exported PNGs and checks:

1. Zero newly introduced black pixels in adjacent upper layers.
2. Exact retention of the core and registration rectangle; top equals core.
3. Zero mismatches against a vertical mirror.
4. Exactly one four-connected artwork component, excluding registration.
5. Zero pixels lost under exact radius-24 rolling-disk opening, plus one connected
   backbone after 19-pixel erosion to detect narrow structural necks.
6. At least 1444 exposed artwork pixels removed at every stage (38 × 38 pixels).
7. Matching dimensions, DPI metadata, binary colors, and separated registration.

Failed sets retain diagnostic PNGs and a report but get no manufacturing ZIP.
Checks establish raster geometry, not material strength or laser calibration.
Kerf, wood grain, thickness, scorch, glue, and real-world scaling still require a
material test cut. The stacking image is an illustration, not a physical simulation.

## Extend

Add a renderer to `laser_art/subjects.py` with `@register(...)`. Return a `Master`
with a persistent connected `core` and identified optional `Component` objects.
Each component has paths, a removal priority, and an optional parent. Attach child
paths exactly to parent paths and remove children before their parents. The layer
engine distributes groups over `N−1` removal stages. Keep new geometry inside the
registration border and pass the full validation before using any exports.

Manufacturing defaults are centralized in `Manufacturing`. The current production
validator deliberately requires the initial 600 DPI / 6900-pixel boundary contract;
changing physical defaults requires updating that validation contract as well.

## Reference-image first-layer proof

To prepare a detailed first layer directly from a supplied black-on-white raster:

```sh
python3 -m laser_art.reference /path/to/reference.png --output outputs/reference-proof
```

This path isolates the largest artwork component apart from a separate outer
frame, mirrors the left half exactly, and scales the reference once. It removes
source islands and reinforces thin strokes around a topology-preserving skeleton
with the same radius-24 disk used in validation. Broad original bands are retained
through disk opening. Background padding prevents clipping at the tight source
crop. The generated `layer_01_bottom.png` has the same 600 DPI and registration
contract as procedural exports. `first_layer_preview.png` is for visual review;
`reference_validation.json` records source provenance, pixel changes, and checks.

This is a **single-layer approval checkpoint**. It does not yet decompose a flat
reference into removable components or certify a multi-layer manufacturing set.
It makes no cross-layer containment or progressive-complexity claim. Approve the
master's visual appearance before implementing its component decomposition.

## Reference-derived second layer

After approving the first layer, derive a simplified second layer with:

```sh
python3 -m laser_art.reference_layers outputs/reference-proof/layer_01_bottom.png --output outputs/reference-layer-2
```

The engine first verifies the master is exactly a union of inscribed radius-24
pixel disks. A reduced-resolution skeleton guides grouping only; it never renders
new artwork. Terminal branches are traced from endpoints to real junctions, with
diagonal pixel shortcuts excluded. Disk centers are assigned to complete mirrored
terminal-scroll groups or the retained structure. Centers protecting the master's
exterior band remain retained. Fine scroll pairs are removed first, by deleting
whole original disk groups. Their overlaps with surviving groups are preserved.

`master_component_centers.npz` and `master_components.json` persist that exact
master decomposition for later work. `layer_02.png` is the full-resolution binary
manufacturing raster; `layer_02_preview.png` is for viewing. The red pixels in
`removed_features_preview.png` show precisely the material removed from layer 1.
`layer_02_validation.json` records actual exported-pixel checks. `--fraction`
controls the fraction of eligible terminal-scroll pairs removed, default 0.65;
it does not represent a fraction of total artwork area.

This command generates **only layer 2**. Later stages need further decomposition
of the retained branches and loops; it does not claim a completed five-layer set.

## Advance to layer 3 from saved groups

```sh
python3 -m laser_art.advance \
  --master outputs/reference-proof/layer_01_bottom.png \
  --components outputs/reference-layer-2 \
  --previous outputs/reference-layer-2/layer_02.png \
  --previous-report outputs/reference-layer-2/layer_02_validation.json \
  --layer 3 --output outputs/reference-layer-3
```

This command verifies the original master checksum, the exact original component
reconstruction, and the prior layer's pixel identity against its removal state.
It then removes the remaining eligible terminal-scroll groups from that same
saved decomposition. The original center coordinates, radii, and ownership are
unchanged. The new exported PNG must be an exact subset of the previous PNG and
retain the original protected core and registration boundary. Full-resolution
connectivity, symmetry, disk-width, and progressive-area checks are rerun.

The output includes the new manufacturing PNG, its preview, a red removal preview
relative to the prior layer, and a validation report with cumulative removal state.
Once terminal groups are exhausted, this command rejects further duplicate layers.
Layers 4 and 5 are produced by the finishing command below, which refines the
retained group without modifying any original disk geometry.


## Finish five layers and visualize the assembled stack

```sh
python3 -m laser_art.finish \
  --master outputs/reference-proof/layer_01_bottom.png \
  --second outputs/reference-layer-2/layer_02.png \
  --third outputs/reference-layer-3/layer_03.png \
  --components outputs/reference-layer-2 \
  --third-report outputs/reference-layer-3/layer_03_validation.json \
  --output outputs/reference-complete
```

This preserves layers 1–3 byte for byte. It partitions the original retained disk
centers into the permanent outline, main vein routes, and remaining decoration.
Routes follow existing reference skeleton branches; they draw no new geometry.
Layer 4 retains outline plus main veins; layer 5 retains the original outline.
All five exported PNGs undergo exact containment, core, symmetry, connectivity,
width, progressive-area, and registration checks together before packaging.

Separate binary manufacturing files are `layer_01_bottom.png`, `layer_02.png`,
`layer_03.png`, `layer_04.png`, and `layer_05_top.png`. They remain at identical
6400 × 7200 dimensions and 600 DPI. `all_layers_preview.png` shows all five
individually. `stacked_green.png` is a full-resolution, aligned top view of the
assembled artwork: each original layer mask is overlaid opaquely, dark green on
the bottom through pale green on top. Registration is excluded. Its smaller
`stacked_green_preview.png` is for viewing. The legend records all five shades
and verifies that each exposed band displays its correct layer color. This is a
color illustration, not a physical simulation of sheet thickness or kerf.

`ginkgo_five_layers_green.zip` contains all five PNGs, individual and combined
previews, the green stack, validation report, and saved original-component data.

## Flow-focused master and balanced component schedule

For an organic reference whose smooth line flow should be preserved:

```sh
python3 -m laser_art.reference outputs/ginkgo-flow-concept/master_concept.png \
  --smooth --output outputs/ginkgo-flow-master
python3 -m laser_art.flow_set outputs/ginkgo-flow-master/layer_01_bottom.png \
  --layers 5 --output outputs/ginkgo-flow-five-layers
```

`--smooth` fits the source's organic skeleton branches once, holds their junctions
fixed, mirrors them exactly, and reinforces the new master to manufacturing width.
It also uses smooth resampling for the original broad bands. Use this option for
organic curves; preserve deliberate corners on architectural or geometric subjects.
All master preparation happens before any layers or component masks are derived.

The flow-set engine partitions the fixed master disks into the permanent outline,
main vein components, and complete attached ornament clusters. Main vein envelopes
follow smooth, tapered routes through existing disk centers. Tips that attach
through a neck below the width requirement remain optional decoration rather than
permanent structural material. No disk center or radius changes during layering.

Fine ornament clusters are removed first, with exposed material area distributed
across the available decoration stages. The penultimate layer retains the main
veins and outline; the top contains only the original outline. The engine accepts
other layer counts when enough complete ornaments exist for meaningful steps.
Every export is validated against its lower layer and the shared original core.

The output contains each PNG separately, all-layer and green-stack previews,
complete component data, the validation report, and a ZIP. Existing design sets
are preserved. Failed candidates remain diagnostic files and do not receive a
manufacturing bundle.

## Preferred: independently smooth curve components

The earlier raster-partition engines can expose irregular remnants at junctions.
For organic artwork, use the curve-component master instead:

```sh
python3 -m laser_art.curve_master outputs/ginkgo-flow-concept/master_concept.png \
  --layers 5 --output outputs/ginkgo-smooth-curve-five-layers
```

This rebuilds **one new master**, guided by the reference, from smooth spline
centerlines and analytic gradual tapers. Every main vein is a complete independent
stroke. Every removable ornament is a complete attached curve group. Junctions are
held fixed; the reference's outline is fitted once as a closed curve. Corners in
non-organic subjects need deliberately preserved geometry; this engine is for
organic references.

Components are rasterized once, cached, and combined into the bottom master.
Layer simplification only subtracts complete cached masks. Removing a scroll
therefore exposes the original parent curve rather than a Voronoi or skeleton
ownership boundary. There is no per-layer smoothing, reconstruction, or line-width
change. The only mask clipping is at the permanent outer silhouette, under its
outline band; parent curves are never clipped around ornament junctions.

`master_curves.json` saves actual curve samples, radius profiles, and removal
stages. `master_component_masks.npz` saves the exact immutable rendered masks.
The report adds an outer-silhouette consistency check to all manufacturing checks.
The master is a new geometric interpretation of the reference, not a promise of
pixel identity with the flattened reference or previous designs.

Regression tests explicitly remove a curved branch from a tapered parent and
verify the result is bit-for-bit identical to the untouched parent component,
including the formerly shared junction. All previous output sets are preserved.

## Parent-following roots and full-length tendril taper

The curve engine now contracts small raster junction clusters into single authored
vertices, eliminating short fat micro-strokes. Widths follow a rooted tendril
network with shared node radii and continuous smoothstep transitions. Free tips
finish at radius 20 pixels (41-pixel diameter), above the 38-pixel material minimum.
The production geometry and final layers still undergo full width validation.

At a main-vein attachment, the tendril starts slightly upstream, follows the
parent curve in its local tangent/normal frame, and gradually peels away on the
intended side. Initial normal offset and its first two derivatives are zero.
Root disks stay inside the parent's material with a checked clearance. This avoids
both the visible circular end cap and the opposite-side shoulder that can remain
after matching only a straight tangent direction. Curve geometry is authored once;
removing components never changes any surviving curve or its taper.

The current result is under `outputs/ginkgo-tapered-tangent-five-layers`. Its ZIP
includes separate layer PNGs, the green stack, close-ups of previous and revised
junctions, root-attachment measurements, exact component masks, and validation.

## Pointed decorative tips (explicit width-policy exception)

Fine points cannot satisfy the uniform 38-pixel width requirement at their ends.
Use `--pointed-tips` only when this decorative-terminal exception is desired:

```sh
python3 -m laser_art.curve_master outputs/ginkgo-flow-concept/master_concept.png \
  --layers 5 --pointed-tips --output outputs/ginkgo-pointed-rim-five-layers
```

Only free, non-load-bearing terminal ends may be pointed. Roots cannot receive
this exception. The terminal radius tapers to zero through a bounded tail region,
with no round end cap. Raster tips use a one-pixel connected apex. All structural
bodies are still rendered as unions of radius-20 disks and must pass the original
38-pixel minimum-width checks, including the eroded-backbone connectivity test.

The application validates each full layer plus a separate structural-body layer.
It checks body pixels are contained in the full layer, making the difference an
explicit set of terminal extensions. The report retains strict all-material width
failures as diagnostics and distinguishes the accepted terminal exceptions from
structural width compliance. `structural_bodies/` contains validation masks, not
additional cutting plies. This mode does **not** claim compliance with a uniform
minimum width at every decorative tip.

The perimeter handling leaves a visible clearance for nearby scrolls, and main
vein end caps fit inside the permanent outline rather than extending along it as
thin colored slivers. The approved natural main-vein paths are retained. Previous
design versions remain unchanged.
