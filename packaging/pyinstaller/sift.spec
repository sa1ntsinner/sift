# PyInstaller spec: one-file `sift` binary with the region data and Textual assets bundled.
# Build:  pyinstaller packaging/pyinstaller/sift.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("steamsift", includes=["data/*.json"])
datas += collect_data_files("textual")
hidden = (collect_submodules("steamsift") + collect_submodules("textual")
          + collect_submodules("keyring.backends") + ["textual_image"])

a = Analysis(
    ["entry.py"],
    pathex=[os.path.abspath(".")],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="sift",
    console=True,
    upx=False,
)
