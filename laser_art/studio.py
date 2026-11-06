"""Browser-friendly, two-stage studio API with a frozen reviewed master."""
import gc
import hashlib
import json
from pathlib import Path
import re
import zipfile

from PIL import Image, ImageOps
from .curve_master import curve_components, rasterize_master, build
from .flow_set import save_art

MAX_LAYERS=12


def validate_options(subject,layers,pointed_tips):
    if not isinstance(subject,str) or not 1<=len(subject.strip())<=200:
        raise ValueError('Please describe your subject in 1–200 characters.')
    if not re.search(r'\b(ginkgo|gingko)\b',subject,re.IGNORECASE):
        raise ValueError('Ginkgo leaf is the currently supported subject. Choose it to continue.')
    if isinstance(layers,bool) or not isinstance(layers,int) or not 2<=layers<=MAX_LAYERS:
        raise ValueError(f'Choose a whole number from 2 to {MAX_LAYERS} layers.')
    if not isinstance(pointed_tips,bool):
        raise ValueError('Please choose a tip style.')


def normalize_reference(source,destination):
    source,destination=Path(source),Path(destination)
    if source.stat().st_size>20*1024*1024:
        raise ValueError('Please use a PNG or JPEG smaller than 20 MB.')
    with Image.open(source) as original:
        if original.format not in ('PNG','JPEG'):
            raise ValueError('Please use a PNG or JPEG reference image.')
        if original.width*original.height>16_000_000:
            raise ValueError('Please resize this reference to at most 16 megapixels.')
        image=ImageOps.exif_transpose(original).convert('RGBA')
        white=Image.new('RGBA',image.size,'white');white.alpha_composite(image)
        image=white.convert('RGB');image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
        if image.width%2:
            canvas=Image.new('RGB',(image.width+1,image.height),'white');canvas.paste(image,(0,0));image=canvas
        if min(image.size)<120:
            raise ValueError('Please use a reference at least 120 pixels on each side.')
        image.save(destination)


def prepare(reference,subject,layers,pointed_tips,workspace,progress=None):
    validate_options(subject,layers,pointed_tips)
    workspace=Path(workspace);workspace.mkdir(parents=True,exist_ok=True)
    normalized=workspace/'reference.png'
    normalize_reference(reference,normalized)
    if progress:progress('trace',0,1)
    settings,components,geometry=curve_components(normalized,pointed_tips=pointed_tips)
    available=min(MAX_LAYERS,len(components))
    if layers>available:
        raise ValueError(f'This artwork supports at most {available} distinct layers. Please choose fewer layers.')
    snapshot={'manufacturing':settings.__dict__,'components':components,'geometry':geometry,
              'pointed_tips':pointed_tips,'subject':subject.strip(),'layers':layers}
    state=rasterize_master(settings,components,pointed_tips,progress)
    master_path=workspace/'reviewed_master.png'
    save_art(state['coverage']>0,state['border'],master_path)
    with Image.open(master_path) as image:
        preview=image.convert('RGB');preview.thumbnail((720,810),Image.Resampling.LANCZOS)
        preview.save(workspace/'master_preview.png')
    snapshot['reviewed_master_sha256']=hashlib.sha256(master_path.read_bytes()).hexdigest()
    (workspace/'snapshot.json').write_text(json.dumps(snapshot))
    del state;gc.collect()
    return {'subject':subject.strip(),'layers':layers,'pointed_tips':pointed_tips,
            'component_count':len(components),'preview_path':str(workspace/'master_preview.png'),
            'master_path':str(master_path),'reviewed_master_sha256':snapshot['reviewed_master_sha256'],
            'manufacturing':settings.__dict__}


def export(workspace,progress=None):
    workspace=Path(workspace)
    snapshot=json.loads((workspace/'snapshot.json').read_text())
    validate_options(snapshot['subject'],snapshot['layers'],snapshot['pointed_tips'])
    output=workspace/'export'
    report=build(workspace/'reference.png',output,snapshot['layers'],snapshot['pointed_tips'],
                 frozen_master=snapshot,progress=progress)
    first=output/'layer_01_bottom.png'
    if hashlib.sha256(first.read_bytes()).hexdigest()!=snapshot['reviewed_master_sha256']:
        for path in output.glob('*.zip'):path.unlink()
        raise ValueError('The exported master differs from the reviewed master. Please create a fresh preview.')
    report['reviewed_master_unchanged']=True
    report['subject']=snapshot['subject']
    (output/'validation_report.json').write_text(json.dumps(report,indent=2))
    (output/'READ_ME.txt').write_text(
        'LAYERLEAF · GINKGO LAYER SET\n\n'
        f"{snapshot['layers']} layers. Stack 01_bottom through the numbered layers, finishing with _top.\n"
        'Manufacturing PNGs: 6400 x 7200 pixels, 600 DPI. Black material; white cutouts.\n'
        'Scale the separate registration rectangle to 11.5 inches EXTERNAL height; exclude it from cutting.\n'
        f"Pointed decorative tips: {'enabled; tips may be below the structural width minimum' if snapshot['pointed_tips'] else 'disabled; uniform width checks apply'}.\n"
        'All structural bridges retain at least 38 pixels at 600 DPI.\n'
        'Preview images are illustrations, not cutting files. Test material and kerf before a full cut.\n'
        'structural_bodies/ contains validation masks, not extra cutting layers.\n')
    name=f"layerleaf-ginkgo-{snapshot['layers']}-layers.zip"
    with zipfile.ZipFile(output/name,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path.suffix!='.zip':archive.write(path,path.relative_to(output))
    for path in output.glob('*.zip'):
        if path.name!=name:path.unlink()
    files=[{'name':name,'path':str(output/name),'mime':'application/zip','kind':'bundle'},
           {'name':'stacked_green.png','path':str(output/'stacked_green.png'),'mime':'image/png','kind':'stack_full'},
           {'name':'stacked_green_preview.png','path':str(output/'stacked_green_preview.png'),'mime':'image/png','kind':'stack'},
           {'name':'all_layers_preview.png','path':str(output/'all_layers_preview.png'),'mime':'image/png','kind':'sheet'},
           {'name':'validation_report.json','path':str(output/'validation_report.json'),'mime':'application/json','kind':'report'}]
    for i in range(snapshot['layers']):
        suffix='_bottom' if i==0 else '_top' if i==snapshot['layers']-1 else ''
        filename=f'layer_{i+1:02d}{suffix}.png'
        files.append({'name':filename,'path':str(output/filename),'mime':'image/png','kind':'layer','index':i+1})
        preview=f'layer_{i+1:02d}{suffix}_preview.png'
        files.append({'name':preview,'path':str(output/preview),'mime':'image/png','kind':'layer_preview','index':i+1})
    return {'subject':snapshot['subject'],'layers':snapshot['layers'],'pointed_tips':snapshot['pointed_tips'],
            'report':report,'files':files,
            'palette':json.loads((output/'green_stack_legend.json').read_text())['colors_bottom_to_top']}
