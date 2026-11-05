"""Create synthetic, non-company images for UI checks only."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

directory = Path(sys.argv[1])
directory.mkdir(parents=True, exist_ok=True)
image = Image.new('RGBA', (2400, 1600), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((300, 180, 2100, 1200), radius=40, fill='#26334b')
draw.rectangle((340, 220, 2060, 1120), fill='#8bb3e0')
draw.polygon([(340, 1120), (1100, 410), (1700, 1120)], fill='#b5d5ea')
draw.polygon([(900, 1120), (1610, 520), (2060, 1120)], fill='#7194bb')
draw.rectangle((1120, 1200, 1280, 1390), fill='#53627a')
draw.rounded_rectangle((850, 1380, 1550, 1440), radius=20, fill='#53627a')
image.save(directory / 'qa-monitor-transparent.png')
print(str(directory / 'qa-monitor-transparent.png'))
