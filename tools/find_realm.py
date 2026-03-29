import os
from pathlib import Path

appdata = os.environ.get('APPDATA', '')
osu_dir = Path(appdata) / 'osu'

if osu_dir.exists():
    for f in osu_dir.glob('client*.realm'):
        print(f)
