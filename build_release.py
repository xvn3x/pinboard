"""Build the portable Windows release with .runtime/Scripts/python.exe."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import importlib.metadata
from app import APP_VERSION

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "build-assets"
ASSETS.mkdir(exist_ok=True)
image = Image.new("RGBA", (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, 255, 255), radius=78, fill="#e60023")
draw.line((87, 182, 87, 76, 144, 76), fill="white", width=27)
draw.arc((111, 76, 184, 149), -90, 90, fill="white", width=27)
draw.line((146, 136, 124, 136), fill="white", width=27)
draw.line((146, 180, 168, 200, 203, 158), fill="white", width=15, joint="curve")
image.save(ASSETS / "pinboard.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
if "--package-only" not in sys.argv:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                    "--name", "Pinboard", "--icon", str(ASSETS / "pinboard.ico"),
                    "--add-data", f"{ROOT / 'web'};web", "--collect-all", "gallery_dl", "--collect-all", "yt_dlp",
                    "--hidden-import", "PIL.Image", str(ROOT / "desktop.py")], cwd=ROOT, check=True)
release = ROOT / "release"
release.mkdir(exist_ok=True)
try:
    shutil.copy2(ROOT / "dist" / "Pinboard.exe", ROOT / "Pinboard.exe")
except PermissionError:
    print("Close the running Pinboard app to replace Pinboard.exe. The new EXE is in dist/.")

# Retain the installed dependencies' notices alongside the distributable.
licenses = ASSETS / "licenses"
licenses.mkdir(exist_ok=True)
versions = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata['Name']
    versions.append(f"{name}=={distribution.version}")
    for file in distribution.files or []:
        if any(part.lower().startswith(('license', 'copying', 'notice')) for part in file.parts):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                destination = licenses / name / file
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
(licenses / 'versions.txt').write_text('\n'.join(sorted(versions)), encoding='utf-8')
with zipfile.ZipFile(release / f"Pinboard-{APP_VERSION}-Windows.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(ROOT / "dist" / "Pinboard.exe", "Pinboard/Pinboard.exe")
    archive.write(ROOT / "QUICKSTART.txt", "Pinboard/Начать здесь.txt")
    archive.write(ROOT / "THIRD_PARTY.md", "Pinboard/THIRD_PARTY.md")
    archive.write(ROOT / "LICENSE", "Pinboard/LICENSE")
    for file in licenses.rglob('*'):
        if file.is_file():
            archive.write(file, 'Pinboard/licenses/' + file.relative_to(licenses).as_posix())

# Explicit allowlist: never distribute settings, downloads, logs or local environments.
source_files = ['app.py', 'desktop.py', 'build_release.py', 'requirements.txt', 'requirements-build.txt',
                'setup.cmd', 'download.cmd', 'Start Pinboard.cmd', 'README.md', 'QUICKSTART.txt',
                'THIRD_PARTY.md', 'LICENSE', '.gitignore']
with zipfile.ZipFile(release / f"Pinboard-{APP_VERSION}-Source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for name in source_files:
        archive.write(ROOT / name, 'Pinboard/' + name)
    for folder in ['web', 'tests', '.github']:
        for file in (ROOT / folder).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:
                archive.write(file, 'Pinboard/' + file.relative_to(ROOT).as_posix())

# gallery-dl is GPL-2.0; provide the exact bundled Python source with each release.
with zipfile.ZipFile(release / f"Pinboard-{APP_VERSION}-Dependency-Sources.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    distribution = importlib.metadata.distribution('gallery-dl')
    for file in distribution.files or []:
        source = Path(distribution.locate_file(file))
        if file.parts[0].startswith('gallery_dl') and '__pycache__' not in file.parts and source.is_file():
            archive.write(source, file.as_posix())
print("Ready:", ROOT / "Pinboard.exe")
