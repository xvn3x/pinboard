# Third-party components

Pinboard is an independent application, not affiliated with Pinterest.
The interface and Pinboard mark are custom local assets.
No Pinterest logo or remotely hosted visual assets are bundled.

- gallery-dl 1.32.1 — GPL-2.0; https://github.com/mikf/gallery-dl/tree/v1.32.1
- yt-dlp 2026.7.4 — Unlicense (some bundled modules have their own licenses); https://github.com/yt-dlp/yt-dlp/tree/2026.07.04
- Requests — Apache-2.0; https://github.com/psf/requests
- Python — PSF License; https://www.python.org/psf/license/
- Pillow — HPND; https://github.com/python-pillow/Pillow
- PyInstaller bootloader — GPL-2.0 with distribution exception; https://pyinstaller.org/en/stable/license.html

Dependency versions are recorded in requirements.txt and requirements-build.txt.
Pinboard is distributed under GPL-2.0 (see LICENSE). The portable archive includes
dependency license texts in licenses/ and the installed versions in licenses/versions.txt.
Each release also provides Pinboard's source and the exact bundled gallery-dl Python
source in separate Source and Dependency-Sources archives. Keep these source archives
available alongside the binary when redistributing. Build instructions are in README.md.
