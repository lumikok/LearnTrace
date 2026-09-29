"""Produce three comparison sketches for the ShiGuang app icon."""

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "design" / "icon-options"
OUT.mkdir(parents=True, exist_ok=True)
S = 3
GREEN = "#1f3831"
PAPER = "#f7f5e9"
GOLD = "#efc879"

def base():
    im = Image.new("RGBA", (256*S, 256*S), (0,0,0,0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0,0,256*S-1,256*S-1), radius=54*S, fill=GREEN)
    return im,d

def b(v): return tuple(int(n*S) for n in v)
def poly(d, points, fill): d.polygon([(x*S,y*S) for x,y in points], fill=fill)

# A — morning light over an open book.
a, d = base()
d.ellipse(b((150,48,192,90)),fill=GOLD)
poly(d, [(43,100),(63,94),(84,94),(103,100),(115,108),(128,121),(128,200),(109,190),(88,185),(65,183),(43,185)], PAPER)
poly(d, [(213,100),(193,94),(172,94),(153,100),(141,108),(128,121),(128,200),(147,190),(168,185),(191,183),(213,185)], PAPER)
d.line((128*S,121*S,128*S,200*S), fill=GREEN, width=6*S)
a.resize((512,512),Image.Resampling.LANCZOS).save(OUT/'a-book-light.png')

# B — a compact calendar with one golden day.
im, d = base()
d.rounded_rectangle(b((49,54,207,206)),radius=21*S,fill=PAPER)
d.rectangle(b((49,88,207,104)),fill=GREEN)
for x in (78,111,144,177):
    for y in (127,159):
        d.rounded_rectangle(b((x-9,y-9,x+9,y+9)),radius=5*S,fill=GREEN)
d.ellipse(b((135,150,153,168)),fill=GOLD)
d.rounded_rectangle(b((77,43,88,68)),radius=5*S,fill=GOLD)
d.rounded_rectangle(b((168,43,179,68)),radius=5*S,fill=GOLD)
im.resize((512,512),Image.Resampling.LANCZOS).save(OUT/'b-calendar-day.png')

# C — focused time: an hourglass and the moment that matters.
im, d = base()
d.rounded_rectangle(b((66,53,190,65)),radius=6*S,fill=PAPER)
d.rounded_rectangle(b((66,191,190,203)),radius=6*S,fill=PAPER)
poly(d,[(78,70),(178,70),(178,80),(140,121),(140,133),(178,177),(178,186),(78,186),(78,177),(116,133),(116,121),(78,80)],PAPER)
poly(d,[(92,82),(164,82),(128,119)],GREEN)
poly(d,[(128,145),(164,175),(92,175)],GREEN)
d.ellipse(b((120,129,136,145)),fill=GOLD)
im.resize((512,512),Image.Resampling.LANCZOS).save(OUT/'c-hourglass.png')
