from dataclasses import asdict
from pathlib import Path
import json
import zipfile
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from .model import Master


def raster_component(component, settings):
    points=[p for path in component.paths for p in path]
    r=settings.radius
    x0=max(0,int(min(p[0] for p in points))-r-3)
    y0=max(0,int(min(p[1] for p in points))-r-3)
    x1=min(settings.width,int(max(p[0] for p in points))+r+4)
    y1=min(settings.height,int(max(p[1] for p in points))+r+4)
    image=Image.new('1',(x1-x0,y1-y0))
    draw=ImageDraw.Draw(image)
    for path in component.paths:
        draw.line([(round(x)-x0,round(y)-y0) for x,y in path],fill=1,width=1)
    mask=ndi.distance_transform_edt(~np.asarray(image,dtype=bool)) <= r
    return (x0,y0,x1,y1),mask


def stamp(target, box, mask, mirrored, value=1):
    x0,y0,x1,y1=box
    target[y0:y1,x0:x1] += mask.astype(target.dtype)*value
    if mirrored:
        target[y0:y1,target.shape[1]-x1:target.shape[1]-x0] += mask[:,::-1].astype(target.dtype)*value


def boundary_mask(s):
    image=Image.new('1',(s.width,s.height))
    ImageDraw.Draw(image).rectangle(s.boundary,outline=1,width=s.boundary_width)
    return np.asarray(image,dtype=bool)


def read_black(path):
    with Image.open(path) as image:
        pixels=np.asarray(image.convert('L'))
        return pixels==0, image.size, image.info.get('dpi'), bool(np.all((pixels==0)|(pixels==255)))


def validate(paths, core, settings, stages):
    border=boundary_mask(settings)
    previous=None
    results=[]
    previous_area=None
    for i,path in enumerate(paths):
        black,size,dpi,binary=read_black(path)
        art=black & ~border
        labels,count=ndi.label(art)  # Four-connected, stricter than diagonal contact.
        del labels
        # Opening with the configured manufacturing disk detects thin strokes.
        # Every structural pixel must be covered by a fully inscribed disk.
        distance=ndi.distance_transform_edt(art)
        erosion=distance>settings.radius
        _, bridge_components=ndi.label(distance>19)
        del distance
        opened=ndi.distance_transform_edt(~erosion)<=settings.radius
        width_violations=int(np.count_nonzero(art & ~opened))
        area=int(art.sum())
        removed=None if previous_area is None else previous_area-area
        containment=0 if previous is None else int(np.count_nonzero(black & ~previous))
        row={
            'file':path.name,'artwork_pixels':area,
            'containment_violations':containment,
            'missing_core_pixels':int(np.count_nonzero(core & ~art)),
            'symmetry_mismatched_pixels':int(np.count_nonzero(black != black[:,::-1])),
            'artwork_connected_components':int(count),
            'minimum_width_uncovered_pixels':width_violations,
            'connected_backbones_after_19px_erosion':int(bridge_components),
            'minimum_width_method':f'Exact rolling-disk opening, radius {settings.radius} px; all structural strokes share this disk',
            'guaranteed_stroke_diameter_pixels':2*settings.radius+1,
            'removed_artwork_pixels':removed,
            'meaningful_removal':removed is None or removed>=38*38,
            'dimensions':list(size),'dpi':list(dpi) if dpi else None,
            'binary_colors':binary,
            'registration_exact':bool(np.array_equal(black & border,border)),
            'registration_separate':not bool(np.any(ndi.binary_dilation(art)&border)),
            'top_is_core_only':bool(np.array_equal(art,core)) if i==len(paths)-1 else None,
        }
        row['passed']=bool(containment==0 and row['missing_core_pixels']==0
            and row['symmetry_mismatched_pixels']==0 and count==1 and width_violations==0
            and bridge_components==1 and row['meaningful_removal'] and size==(settings.width,settings.height)
            and dpi and all(abs(d-settings.dpi)<0.02 for d in dpi) and binary
            and row['registration_exact'] and row['registration_separate']
            and (i!=len(paths)-1 or row['top_is_core_only']))
        results.append(row)
        previous=black
        previous_area=area
    x0,y0,x1,y1=settings.boundary
    return {'passed':all(r['passed'] for r in results) and (y1-y0+1)==6900 and settings.dpi==600,
            'manufacturing':asdict(settings),
            'scaling_boundary_external_height_pixels':y1-y0+1,
            'scaling_boundary_external_height_inches':(y1-y0+1)/settings.dpi,
            'minimum_required_width_pixels':38,
            'layer_order':'bottom (most detailed) to top (outline only)',
            'removal_stages':[[c.id for c in stage] for stage in stages],
            'layers':results}


def previews(paths, output):
    thumbnails=[]
    for path in paths:
        with Image.open(path) as im:
            thumb=im.convert('RGB'); thumb.thumbnail((420,480))
        thumbnails.append(thumb)
    sheet=Image.new('RGB',(440*len(paths),540),'#ede8df')
    draw=ImageDraw.Draw(sheet)
    for i,thumb in enumerate(thumbnails):
        sheet.paste(thumb,(i*440+10,35))
        draw.text((i*440+15,12),f'Layer {i+1} · {"bottom" if i==0 else "top" if i==len(paths)-1 else "middle"}',fill='#302b24')
    sheet.save(output/'layers_preview.png')
    # An illustrative exploded stack uses the actual exported masks; it is not
    # a machining image or a simulation of kerf, grain, lighting, or glue.
    stack=Image.new('RGB',(1100,1050),'#e7dfd1')
    for i,thumb in enumerate(thumbnails):
        small=thumb.resize((550,620))
        mask=small.convert('L').point(lambda p:255 if p<128 else 0)
        wood=Image.new('RGB',small.size,('#6b3f25','#8b5630','#ad7847','#c99a61','#e0bb80')[i%5])
        pos=(70+i*90,350-i*65)
        shadow=Image.new('RGB',small.size,'#4a3324')
        stack.paste(shadow,(pos[0]+4,pos[1]+8),mask)
        stack.paste(wood,pos,mask)
    ImageDraw.Draw(stack).text((30,25),'Exploded stacking illustration · bottom to top',fill='#302b24')
    stack.save(output/'stacking_preview.png')


def generate(master: Master, layers: int, output):
    stages=master.removal_stages(layers)
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty to avoid overwriting an earlier design.')
    output.mkdir(parents=True,exist_ok=True)
    (output/'master.json').write_text(json.dumps(asdict(master),indent=2))
    s=master.settings
    coverage=np.zeros((s.height,s.width),dtype=np.int16)
    box,mask=raster_component(master.core,s)
    stamp(coverage,box,mask,master.core.mirror)
    core=coverage>0
    # Cached immutable component masks are reused for removal, never redrawn.
    cache={}
    for component in master.components:
        box,mask=raster_component(component,s)
        cache[component.id]=(box,mask)
        stamp(coverage,box,mask,component.mirror)
    border=boundary_mask(s)
    paths=[]
    for i in range(layers):
        if i:
            for component in stages[i-1]:
                box,mask=cache[component.id]
                stamp(coverage,box,mask,component.mirror,-1)
        suffix='_bottom' if i==0 else '_top' if i==layers-1 else ''
        path=output/f'layer_{i+1:02d}{suffix}.png'
        pixels=np.where((coverage>0)|border,0,255).astype(np.uint8)
        Image.fromarray(pixels).convert('1').save(path,dpi=(s.dpi,s.dpi))
        paths.append(path)
        print(f'Exported {path.name}',flush=True)
    del cache,coverage
    report=validate(paths,core,s,stages)
    (output/'validation_report.json').write_text(json.dumps(report,indent=2))
    if not report['passed']:
        raise ValueError(f'Validation failed. Diagnostic PNGs and report retained in {output}; no manufacturing ZIP created.')
    previews(paths,output)
    with zipfile.ZipFile(output/'manufacturing_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in paths+[output/'layers_preview.png',output/'stacking_preview.png',
                           output/'validation_report.json',output/'master.json']:
            archive.write(path,path.name)
    print(f'All {layers} layers passed; bundle: {output / "manufacturing_bundle.zip"}',flush=True)
    return report
