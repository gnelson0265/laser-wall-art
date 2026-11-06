"""Package the same tested Python engine for the static GitHub Pages site."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/'docs'
with zipfile.ZipFile(SITE/'engine.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((ROOT/'laser_art').glob('*.py')):archive.write(path,path.relative_to(ROOT))
(SITE/'engine-manifest.json').write_text(json.dumps({'sha256':hashlib.sha256((SITE/'engine.zip').read_bytes()).hexdigest(),
 'runtime':'0.28.3','packages':['numpy','scipy','pillow']},indent=2))
print('Packaged browser engine:',(SITE/'engine.zip').stat().st_size,'bytes')
