"""Recrear el icono multirresolución desde el SVG fuente."""
from pathlib import Path
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image
root=Path(__file__).resolve().parents[1]
image=QImage(256,256,QImage.Format.Format_ARGB32);image.fill(0)
p=QPainter(image);QSvgRenderer(str(root/"assets/headmouse.svg")).render(p);p.end()
png=root/"assets/headmouse.png";image.save(str(png))
Image.open(png).save(root/"assets/headmouse.ico",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
