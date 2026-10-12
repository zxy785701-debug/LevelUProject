"""Copy prototype artwork and CSS without changing the originals."""
from pathlib import Path
from PIL import Image
import re

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "prototype/assets"
dst = ROOT / "frontend/src/assets"
dst.mkdir(parents=True, exist_ok=True)
for name in ("u-book", "pencil", "paper"):
    im = Image.open(src / f"{name}.png")
    im.thumbnail((400, 460), Image.Resampling.LANCZOS)
    im.save(dst / f"{name}.png", optimize=True)
# Keep the original token values and component rules. Outer gallery rules are overridden in app.scss.
css = (src / "style.css").read_text(encoding="utf-8").replace(":root", "page, :root")
(ROOT / "frontend/src/prototype.scss").write_text(css, encoding="utf-8")
(ROOT / "frontend/src/footer.scss").write_text((src / "refined-footer.css").read_text(encoding="utf-8"), encoding="utf-8")
ui = (src / "ui.js").read_text(encoding="utf-8")
paths = re.findall(r"(\w+):'([^']+)'", ui.split("const icon=")[0])
icons = dst / "icons"
icons.mkdir(exist_ok=True)
for name, path in paths:
    (icons / f"{name}.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#202a3d" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="{path}"/></svg>', encoding="utf-8")
print("Original artwork copied and resized; original files preserved.")
