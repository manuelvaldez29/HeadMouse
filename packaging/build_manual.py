"""HTML local accesible a partir del manual Markdown versionado."""
from pathlib import Path
from html import escape
import re
root=Path(__file__).resolve().parents[1]
def inline(text):
    text=escape(text)
    return re.sub(r'`([^`]+)`',r'<code>\1</code>',text)
out=[];paragraph=[];kind=None
def flush():
    if paragraph:out.append('<p>'+inline(' '.join(paragraph))+'</p>');paragraph.clear()
def close_list():
    global kind
    if kind:out.append('</'+kind+'>');kind=None
for line in (root/'docs/WINDOWS_USER_MANUAL.md').read_text(encoding='utf-8').splitlines():
    if line.startswith('#'):
        flush();close_list();level=len(line)-len(line.lstrip('#'));out.append(f'<h{level}>'+inline(line[level:].strip())+f'</h{level}>')
    elif line.startswith('- '):
        flush()
        if kind!='ul':close_list();kind='ul';out.append('<ul>')
        out.append('<li>'+inline(line[2:])+'</li>')
    elif not line.strip():flush();close_list()
    elif kind:out.append('<li>'+inline(line.strip())+'</li>')
    else:paragraph.append(line.strip())
flush();close_list()
html='''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Manual HeadMouse</title><style>body{font:18px/1.65 system-ui,sans-serif;color:#172332;max-width:900px;margin:3rem auto;padding:0 1.5rem}h1,h2{line-height:1.25}h1{color:#14796d}h2{margin-top:2rem}code{background:#edf4f3;padding:.1rem .3rem;overflow-wrap:anywhere}li{margin:.4rem 0}@media print{body{font-size:12pt;margin:0}}</style><main>'''+''.join(out)+'</main></html>'
(root/'docs/Manual.html').write_text(html,encoding='utf-8')
