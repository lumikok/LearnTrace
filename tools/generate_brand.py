"""Render the approved notebook/activity-grid mark. Requires Pillow for exports."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'static' / 'brand'
OUT.mkdir(parents=True, exist_ok=True)
GREEN, PAPER, SPINE, GOLD = '#1f3831', '#f7f5e9', '#e9e7db', '#d9b15f'
tiles = [(89,105,'#a9bb91'), (123,105,'#819b7c'), (157,105,GREEN),
         (89,139,'#819b7c'), (123,139,GOLD), (157,139,GREEN)]
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="54" fill="{GREEN}"/>',
       f'<rect x="49" y="53" width="158" height="174" rx="20" fill="{SPINE}"/>',
       f'<path d="M70 53H187Q207 53 207 73V207Q207 227 187 227H70Z" fill="{PAPER}"/>',
       f'<path d="M166 38Q166 33 171 33H181Q186 33 186 38V68L176 62L166 68Z" fill="{GOLD}"/>']
svg.extend(f'<rect x="{x}" y="{y}" width="27" height="27" rx="7" fill="{color}"/>' for x,y,color in tiles)
svg.append('</svg>')
(OUT / 'icon.svg').write_text('\n'.join(svg), encoding='utf-8')

scale = 4
im = Image.new('RGBA', (1024,1024))
d = ImageDraw.Draw(im)
def box(*values): return tuple(v*scale for v in values)
d.rounded_rectangle(box(0,0,256,256),radius=54*scale,fill=GREEN)
d.rounded_rectangle(box(49,53,207,227),radius=20*scale,fill=SPINE)
d.rounded_rectangle(box(70,53,207,227),radius=20*scale,fill=PAPER)
d.rectangle(box(70,53,90,227),fill=PAPER)
d.rounded_rectangle(box(166,33,186,61),radius=5*scale,fill=GOLD)
d.polygon([box(166,38),box(186,38),box(186,68),box(176,62),box(166,68)],fill=GOLD)
for x,y,color in tiles:
    d.rounded_rectangle(box(x,y,x+27,y+27),radius=7*scale,fill=color)
im.resize((512,512),Image.Resampling.LANCZOS).save(OUT/'icon-512.png')
im.resize((256,256),Image.Resampling.LANCZOS).save(OUT/'app.ico',format='ICO',sizes=[(s,s) for s in (16,24,32,48,64,128,256)])
print('Brand assets written to', OUT)
