"""Construit un exécutable autonome (Windows : dist/Convertisseur.exe)."""
import os
import shutil
from pathlib import Path

import imageio_ffmpeg
import PyInstaller.__main__
from deno import find_deno_bin

ici = Path(__file__).resolve().parent
bin_dir = ici / "build" / "bin"
shutil.rmtree(bin_dir, ignore_errors=True)
bin_dir.mkdir(parents=True)

ext = ".exe" if os.name == "nt" else ""
shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(), bin_dir / f"ffmpeg{ext}")
shutil.copy(find_deno_bin(), bin_dir / f"deno{ext}")

args = [
    str(ici / "convertisseur.py"),
    "--name=Convertisseur",
    "--onefile",
    "--windowed",
    "--noconfirm",
    f"--add-binary={bin_dir}{os.pathsep}bin",
    "--collect-data=yt_dlp_ejs",
    "--collect-all=curl_cffi",
    "--collect-all=tkinterdnd2",
]
if (ici / "icone.ico").exists():
    args.append(f"--icon={ici / 'icone.ico'}")
PyInstaller.__main__.run(args)
