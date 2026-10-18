"""Conversion locale de fichiers vidéo, audio et image avec FFmpeg.

Aucune dépendance à l'interface : ce module construit et exécute les
commandes FFmpeg, et peut être testé seul.
"""

import os
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

# Évite l'ouverture d'une console noire sous Windows (exécutable --windowed).
SANS_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

EXT_VIDEO = {
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".asf", ".flv",
    ".f4v", ".mpg", ".mpeg", ".m2v", ".vob", ".ts", ".mts", ".m2ts", ".3gp",
    ".3g2", ".ogv", ".divx", ".rm", ".rmvb", ".mxf", ".dv", ".y4m", ".nut",
}
EXT_AUDIO = {
    ".mp3", ".m4a", ".m4b", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus",
    ".wma", ".aiff", ".aif", ".aifc", ".ac3", ".eac3", ".dts", ".ape", ".wv",
    ".mka", ".amr", ".mp2", ".au", ".caf", ".tta", ".spx", ".alac", ".w64",
}
EXT_IMAGE = {
    ".png", ".apng", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".bmp", ".dib",
    ".tif", ".tiff", ".gif", ".ico", ".cur", ".avif", ".heic", ".heif", ".tga",
    ".jp2", ".j2k", ".jxl", ".qoi", ".ppm", ".pgm", ".pbm", ".pnm", ".pcx",
    ".dds", ".exr", ".hdr", ".dpx", ".sgi", ".xbm", ".xwd", ".psd",
}
# Images qui peuvent contenir une animation (lisibles comme une vidéo).
EXT_ANIMEES = {".gif", ".apng"}
EXT_MEDIAS = EXT_VIDEO | EXT_AUDIO | EXT_IMAGE


class Annule(Exception):
    pass


# --------------------------------------------------------------- formats ---

@dataclass(frozen=True)
class Format:
    cle: str
    nom: str
    ext: str
    categorie: str          # "video", "anim", "audio" ou "image"
    muxer: str
    detail: str = ""
    vcodecs: tuple = ()     # vidéo : codecs proposés, le premier par défaut
    acodec: str = ""        # vidéo : encodeur audio
    encodeur: str = ""      # anim / audio / image : encodeur utilisé
    avec_perte: bool = True
    frequences: tuple = ()  # audio : fréquences acceptées (vide = toutes)

    @property
    def libelle(self):
        return f"{self.nom}  ·  {self.detail}" if self.detail else self.nom


FORMATS = [
    # Vidéo
    Format("mp4", "MP4", ".mp4", "video", "mp4", "le plus compatible",
           ("h264", "h265", "av1", "mpeg4"), "aac"),
    Format("mkv", "MKV", ".mkv", "video", "matroska", "polyvalent",
           ("h264", "h265", "vp9", "av1", "mpeg4", "mpeg2"), "aac"),
    Format("webm", "WebM", ".webm", "video", "webm", "pour le web",
           ("vp9", "av1", "vp8"), "libopus"),
    Format("mov", "MOV", ".mov", "video", "mov", "Apple, montage",
           ("h264", "h265", "prores"), "aac"),
    Format("avi", "AVI", ".avi", "video", "avi", "anciens lecteurs",
           ("mpeg4", "h264"), "libmp3lame"),
    Format("m4v", "M4V", ".m4v", "video", "mp4", "iTunes, Apple",
           ("h264", "h265"), "aac"),
    Format("wmv", "WMV", ".wmv", "video", "asf", "Windows Media",
           ("wmv2",), "wmav2"),
    Format("flv", "FLV", ".flv", "video", "flv", "Flash",
           ("h264",), "aac"),
    Format("ts", "TS", ".ts", "video", "mpegts", "diffusion TV",
           ("h264", "h265", "mpeg2"), "aac"),
    Format("mpg", "MPEG", ".mpg", "video", "mpeg", "MPEG-2, DVD",
           ("mpeg2",), "mp2"),
    Format("3gp", "3GP", ".3gp", "video", "3gp", "anciens téléphones",
           ("h264", "mpeg4"), "aac"),
    Format("ogv", "OGV", ".ogv", "video", "ogg", "format libre",
           ("theora",), "libvorbis"),
    # Animations
    Format("gif", "GIF animé", ".gif", "anim", "gif", "boucle sans son",
           encodeur="gif"),
    Format("webp_anim", "WebP animé", ".webp", "anim", "webp",
           "plus léger que le GIF", encodeur="libwebp_anim"),
    # Audio
    Format("mp3", "MP3", ".mp3", "audio", "mp3", "universel",
           encodeur="libmp3lame"),
    Format("m4a", "M4A (AAC)", ".m4a", "audio", "ipod", "Apple, smartphones",
           encodeur="aac"),
    Format("opus", "Opus", ".opus", "audio", "opus", "excellent à bas débit",
           encodeur="libopus", frequences=(48000, 24000, 16000, 8000)),
    Format("ogg", "OGG Vorbis", ".ogg", "audio", "ogg", "format libre",
           encodeur="libvorbis"),
    Format("wma", "WMA", ".wma", "audio", "asf", "Windows Media",
           encodeur="wmav2"),
    Format("ac3", "AC3", ".ac3", "audio", "ac3", "Dolby Digital",
           encodeur="ac3", frequences=(48000, 44100, 32000)),
    Format("flac", "FLAC", ".flac", "audio", "flac", "sans perte",
           encodeur="flac", avec_perte=False),
    Format("alac", "M4A (ALAC)", ".m4a", "audio", "ipod", "sans perte Apple",
           encodeur="alac", avec_perte=False),
    Format("wav", "WAV", ".wav", "audio", "wav", "non compressé",
           encodeur="pcm_s16le", avec_perte=False),
    Format("aiff", "AIFF", ".aiff", "audio", "aiff", "non compressé Apple",
           encodeur="pcm_s16be", avec_perte=False),
    Format("wv", "WavPack", ".wv", "audio", "wv", "sans perte",
           encodeur="wavpack", avec_perte=False),
    # Image
    Format("png", "PNG", ".png", "image", "image2", "sans perte, transparence",
           encodeur="png", avec_perte=False),
    Format("jpg", "JPEG", ".jpg", "image", "image2", "photos",
           encodeur="mjpeg"),
    Format("webp", "WebP", ".webp", "image", "webp", "léger, pour le web",
           encodeur="libwebp"),
    Format("avif", "AVIF", ".avif", "image", "avif", "très léger",
           encodeur="libaom-av1"),
    Format("jxl", "JPEG XL", ".jxl", "image", "image2", "nouvelle génération",
           encodeur="libjxl"),
    Format("bmp", "BMP", ".bmp", "image", "image2", "non compressé",
           encodeur="bmp", avec_perte=False),
    Format("tiff", "TIFF", ".tiff", "image", "image2", "impression, archives",
           encodeur="tiff", avec_perte=False),
    Format("gif_img", "GIF", ".gif", "image", "gif", "256 couleurs",
           encodeur="gif", avec_perte=False),
    Format("ico", "ICO", ".ico", "image", "ico", "icône, 256 px max",
           encodeur="png", avec_perte=False),
    Format("tga", "TGA", ".tga", "image", "image2", "jeux, 3D",
           encodeur="targa", avec_perte=False),
    Format("jp2", "JPEG 2000", ".jp2", "image", "image2", "archives, cinéma",
           encodeur="libopenjpeg", avec_perte=False),
    Format("qoi", "QOI", ".qoi", "image", "image2", "sans perte, rapide",
           encodeur="qoi", avec_perte=False),
    Format("ppm", "PPM", ".ppm", "image", "image2", "brut",
           encodeur="ppm", avec_perte=False),
]
FORMATS_PAR_CLE = {f.cle: f for f in FORMATS}

# Codecs vidéo : (nom affiché, encodeurs FFmpeg par ordre de préférence).
CODECS_VIDEO = {
    "h264": ("H.264", ("libx264",)),
    "h265": ("H.265 / HEVC", ("libx265",)),
    "vp9": ("VP9", ("libvpx-vp9",)),
    "vp8": ("VP8", ("libvpx",)),
    "av1": ("AV1", ("libsvtav1", "libaom-av1", "librav1e")),
    "mpeg4": ("MPEG-4 (Xvid)", ("libxvid", "mpeg4")),
    "mpeg2": ("MPEG-2", ("mpeg2video",)),
    "wmv2": ("WMV 8", ("wmv2",)),
    "theora": ("Theora", ("libtheora",)),
    "prores": ("ProRes 422", ("prores_ks",)),
}
COPIE = "copie"
NOM_COPIE = "Copier sans réencoder"

# Encodeurs dont on peut régler la vitesse (compromis vitesse / taille).
AVEC_VITESSE = {"libx264", "libx265", "libvpx-vp9", "libvpx", "libsvtav1",
                "libaom-av1", "librav1e", "libwebp_anim"}

ROTATIONS = {
    "Aucune": None,
    "90° horaire": "transpose=1",
    "90° antihoraire": "transpose=2",
    "180°": "hflip,vflip",
    "Miroir horizontal": "hflip",
    "Miroir vertical": "vflip",
}

# Formats sans canal alpha : la transparence est remplacée par du blanc.
SANS_ALPHA = {"jpg", "ppm"}


# ------------------------------------------------------------- capacités ---

def _lancer(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL,
                          creationflags=SANS_CONSOLE, **kw)


class Capacites:
    """Encodeurs et formats de sortie disponibles dans ce FFmpeg."""

    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg
        self.encodeurs = self._liste("-encoders")
        self.muxers = self._liste("-muxers")

    def _liste(self, option):
        try:
            sortie = _lancer([self.ffmpeg, "-hide_banner", option],
                             timeout=20).stdout
        except Exception:
            return set()
        noms = set()
        apres = False
        for ligne in sortie.splitlines():
            if not apres:
                apres = ligne.strip().startswith("--")
                continue
            morceaux = ligne.split()
            if len(morceaux) >= 2:
                noms.update(morceaux[1].split(","))
        return noms

    def encodeur_video(self, codec):
        for enc in CODECS_VIDEO[codec][1]:
            if enc in self.encodeurs:
                return enc
        return None

    def codecs_video(self, fmt):
        return [c for c in fmt.vcodecs if self.encodeur_video(c)]

    def supporte(self, fmt):
        if fmt.muxer not in self.muxers:
            return False
        if fmt.categorie == "video":
            return bool(self.codecs_video(fmt)) and fmt.acodec in self.encodeurs
        return fmt.encodeur in self.encodeurs

    def formats(self):
        return [f for f in FORMATS if self.supporte(f)]


# ---------------------------------------------------------------- analyse ---

@dataclass
class Media:
    chemin: Path
    type: str = "inconnu"   # "video", "audio", "image" ou "inconnu"
    duree: float = None
    largeur: int = None
    hauteur: int = None
    fps: float = None
    audio: bool = False
    frequence: int = None
    alpha: bool = False
    erreur: str = None

    @property
    def animable(self):
        return self.chemin.suffix.lower() in EXT_ANIMEES

    def resume(self):
        morceaux = []
        if self.largeur and self.hauteur and self.type in ("video", "image"):
            morceaux.append(f"{self.largeur}×{self.hauteur}")
        if self.type == "audio" and self.frequence:
            morceaux.append(f"{self.frequence / 1000:g} kHz")
        if self.duree and self.type in ("video", "audio"):
            morceaux.append(format_duree(self.duree))
        return "  ·  ".join(morceaux)


_RE_DUREE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_RE_VIDEO = re.compile(r"Stream #\S+.*?: Video: (.*)")
_RE_TAILLE = re.compile(r",\s*(\d+)x(\d+)")
_RE_FPS = re.compile(r"([\d.]+) (?:fps|tbr)")
_RE_AUDIO = re.compile(r"Stream #\S+.*?: Audio: .*?(\d+) Hz")
_RE_ALPHA = re.compile(r"\b(rgba|bgra|argb|abgr|ya8|ya16\w*|rgba64\w*|"
                       r"yuva\w+|pal8|gbrap\w*)\b")


def analyser(ffmpeg, chemin):
    """Renvoie un Media décrivant `chemin` (lu par FFmpeg, sans ffprobe)."""
    chemin = Path(chemin)
    media = Media(chemin)
    try:
        sortie = _lancer([ffmpeg, "-hide_banner", "-i", str(chemin)],
                         timeout=30).stderr
    except Exception as e:  # noqa: BLE001
        media.erreur = f"Analyse impossible : {e}"
        return media

    m = _RE_DUREE.search(sortie)
    if m:
        h, mi, s = m.groups()
        media.duree = int(h) * 3600 + int(mi) * 60 + float(s)

    video = False
    for ligne in sortie.splitlines():
        mv = _RE_VIDEO.search(ligne)
        if mv and "(attached pic)" not in ligne and not video:
            video = True
            details = mv.group(1)
            mt = _RE_TAILLE.search(details)
            if mt:
                media.largeur, media.hauteur = int(mt[1]), int(mt[2])
            mf = _RE_FPS.search(details)
            if mf:
                media.fps = float(mf[1])
            media.alpha = bool(_RE_ALPHA.search(details))
        ma = _RE_AUDIO.search(ligne)
        if ma and not media.audio:
            media.audio = True
            media.frequence = int(ma[1])

    ext = chemin.suffix.lower()
    if ext in EXT_IMAGE and video:
        media.type = "image"
    elif ext in EXT_AUDIO and media.audio:
        media.type = "audio"
    elif video:
        courte = media.duree is None or media.duree < 0.1
        media.type = "image" if courte and ext not in EXT_VIDEO else "video"
    elif media.audio:
        media.type = "audio"
    else:
        derniere = [l for l in sortie.strip().splitlines() if l.strip()]
        media.erreur = ("Fichier illisible ou format non reconnu."
                        if not derniere else _nettoyer(derniere[-1]))
    return media


def _nettoyer(ligne):
    ligne = ligne.strip()
    if ": " in ligne and ligne.split(": ", 1)[0].endswith(
            tuple(EXT_MEDIAS | {"]"})):
        ligne = ligne.split(": ", 1)[1]
    return ligne


def incompatibilite(media, fmt):
    """Renvoie None si `media` peut être converti en `fmt`, sinon la raison."""
    if media.erreur or media.type == "inconnu":
        return media.erreur or "Fichier illisible."
    cat = fmt.categorie
    if cat in ("video", "anim"):
        if media.type == "video" or (media.type == "image" and media.animable):
            return None
        return "Pas de piste vidéo à convertir."
    if cat == "audio":
        if media.audio:
            return None
        return "Pas de piste audio à convertir."
    if media.type in ("image", "video"):
        return None
    return "Un fichier audio ne peut pas devenir une image."


# --------------------------------------------------------------- options ---

QUALITES = ["Très haute", "Haute", "Moyenne", "Faible"]
VITESSES = ["Rapide", "Normale", "Lente"]


@dataclass
class Options:
    # Vidéo
    vcodec: str = "h264"
    qualite: int = 1            # index dans QUALITES
    hauteur: int = None         # côté le plus court, ex. 720 ; None = origine
    fps: float = None
    vitesse: int = 1            # index dans VITESSES
    son: object = 192           # kbit/s, "copie" ou "aucun"
    # Animation
    largeur_anim: int = 480
    fps_anim: float = 15
    # Audio
    debit: int = 320
    frequence: int = None
    canaux: int = None
    normaliser: bool = False
    # Image : ("max", px), ("pct", %) ou None
    taille: tuple = None
    # Commun
    rotation: str = "Aucune"
    debut: float = None
    fin: float = None


def lire_temps(texte):
    """« 83 », « 1:23 », « 0:01:23.5 » -> secondes (None si vide)."""
    texte = texte.strip().replace(",", ".")
    if not texte:
        return None
    parties = texte.split(":")
    if len(parties) > 3:
        raise ValueError(texte)
    total = 0.0
    for p in parties:
        v = float(p)
        if v < 0:
            raise ValueError(texte)
        total = total * 60 + v
    return total


def format_duree(s):
    s = int(round(s))
    h, reste = divmod(s, 3600)
    m, s = divmod(reste, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ------------------------------------------------------- construction ---

def _pair(expr):
    return f"trunc(({expr})/2)*2"


def _echelle_video(hauteur):
    """Réduit le côté le plus court à `hauteur` (jamais d'agrandissement) et
    garantit des dimensions paires, exigées par la plupart des codecs."""
    if not hauteur:
        return f"scale={_pair('iw')}:{_pair('ih')}"
    v = "\\,"  # virgule échappée pour le graphe de filtres
    w_court = _pair(f"min({hauteur}{v}iw)")
    h_court = _pair(f"min({hauteur}{v}ih)")
    w = f"if(gte(iw{v}ih){v}-2{v}{w_court})"
    h = f"if(gte(iw{v}ih){v}{h_court}{v}-2)"
    return f"scale=w={w}:h={h}"


def _echelle_max(cote, flags=""):
    """Le côté le plus long ne dépasse pas `cote` pixels."""
    w = rf"if(gte(iw\,ih)\,min({cote}\,iw)\,-1)"
    h = rf"if(gte(iw\,ih)\,-1\,min({cote}\,ih))"
    return f"scale=w={w}:h={h}{flags}"


_PALETTE = ("split[a][b];[a]palettegen=max_colors={n}:stats_mode={mode}[p];"
            "[b][p]paletteuse=dither=sierra2_4a")
_SUR_BLANC = ("split[f][b];[b]drawbox=c=white:t=fill:replace=1[w];"
              "[w][f]overlay=format=auto")


def _args_video(enc, q, vitesse):
    v = vitesse
    if enc == "libx264":
        return ["-crf", str((17, 20, 23, 28)[q]),
                "-preset", ("veryfast", "medium", "slow")[v],
                "-pix_fmt", "yuv420p"]
    if enc == "libx265":
        return ["-crf", str((20, 23, 26, 30)[q]),
                "-preset", ("veryfast", "medium", "slow")[v],
                "-pix_fmt", "yuv420p", "-x265-params", "log-level=error"]
    if enc == "libvpx-vp9":
        return ["-crf", str((24, 31, 36, 42)[q]), "-b:v", "0",
                "-deadline", "good", "-cpu-used", str((5, 3, 1)[v]),
                "-row-mt", "1", "-pix_fmt", "yuv420p"]
    if enc == "libvpx":
        return ["-crf", str((6, 10, 20, 30)[q]),
                "-b:v", ("12M", "6M", "3M", "1500k")[q],
                "-deadline", "good", "-cpu-used", str((8, 4, 2)[v]),
                "-pix_fmt", "yuv420p"]
    if enc == "libsvtav1":
        return ["-crf", str((24, 30, 36, 44)[q]),
                "-preset", str((10, 8, 5)[v]), "-pix_fmt", "yuv420p"]
    if enc == "libaom-av1":
        return ["-crf", str((24, 30, 36, 44)[q]), "-b:v", "0",
                "-cpu-used", str((8, 6, 4)[v]), "-row-mt", "1",
                "-pix_fmt", "yuv420p"]
    if enc == "librav1e":
        return ["-qp", str((60, 80, 100, 130)[q]),
                "-speed", str((10, 6, 4)[v]), "-pix_fmt", "yuv420p"]
    if enc in ("libxvid", "mpeg4", "mpeg2video", "wmv2"):
        return ["-q:v", str((2, 4, 6, 9)[q]), "-pix_fmt", "yuv420p"]
    if enc == "libtheora":
        return ["-q:v", str((9, 7, 5, 3)[q]), "-pix_fmt", "yuv420p"]
    if enc == "prores_ks":
        return ["-profile:v", str((3, 2, 1, 0)[q]),
                "-pix_fmt", "yuv422p10le"]
    return []


_DEBIT_MAX = {"wmav2": 192, "mp2": 384, "libopus": 256, "ac3": 640}
# Vorbis en mode qualité : fonctionne aussi en mono, contrairement au débit.
_VORBIS_Q = ((300, 9), (240, 8), (180, 6), (150, 5), (120, 4), (90, 2))


def _args_audio(enc, kbps):
    if enc in ("flac", "alac", "wavpack") or enc.startswith("pcm_"):
        return ["-c:a", enc]
    if enc == "libvorbis":
        q = next((q for seuil, q in _VORBIS_Q if kbps >= seuil), 0)
        return ["-c:a", enc, "-q:a", str(q)]
    kbps = min(kbps, _DEBIT_MAX.get(enc, 320))
    args = ["-c:a", enc, "-b:a", f"{kbps}k"]
    if enc == "aac" and kbps > 256:
        args[-1] = "256k"  # au-delà, l'encodeur AAC n'apporte plus rien
    return args


_FREQUENCES = {"libopus": (48000, 24000, 16000, 12000, 8000),
               "ac3": (48000, 44100, 32000)}


def _filtres_audio(media, o, args, enc):
    """Ajoute normalisation, fréquence et canaux à `args`."""
    if o.normaliser:
        args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    frequence = o.frequence
    if o.normaliser and not frequence:
        # loudnorm sort en 192 kHz : on revient à la fréquence d'origine
        # (48 kHz au plus, et une valeur que l'encodeur accepte).
        frequence = min(media.frequence or 48000, 48000)
        permises = _FREQUENCES.get(enc)
        if permises and frequence not in permises:
            frequence = permises[0]
    if frequence:
        args += ["-ar", str(frequence)]
    if o.canaux:
        args += ["-ac", str(o.canaux)]


def construire_commande(ffmpeg, caps, media, fmt, o, sortie):
    """Renvoie (commande, durée attendue en secondes ou None)."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats"]
    capture = fmt.categorie == "image" and media.type == "video"
    if media.type == "image":
        o = replace(o, debut=None, fin=None)  # une image n'a pas de durée
    if o.debut:
        cmd += ["-ss", f"{o.debut:.3f}"]
    cmd += ["-i", str(media.chemin)]

    duree = media.duree
    if capture:
        duree = None
    elif o.fin is not None:
        duree = max(o.fin - (o.debut or 0), 0.001)
        cmd += ["-t", f"{duree:.3f}"]
    elif o.debut and duree:
        duree = max(duree - o.debut, 0.001)

    cmd += ["-map_metadata", "0"]
    rotation = ROTATIONS.get(o.rotation)
    filtres = [rotation] if rotation else []
    cat = fmt.categorie

    if cat == "video":
        cmd += ["-map", "0:V:0"]
        if o.son != "aucun" and media.audio:
            cmd += ["-map", "0:a?"]
        if o.vcodec == COPIE:
            cmd += ["-c:v", "copy"]
        else:
            enc = caps.encodeur_video(o.vcodec)
            if o.fps:
                filtres.append(f"fps={o.fps:g}")
            filtres.append(_echelle_video(o.hauteur))
            cmd += ["-vf", ",".join(filtres), "-c:v", enc]
            cmd += _args_video(enc, o.qualite, o.vitesse)
            if enc == "libx265" and fmt.muxer in ("mp4", "mov"):
                cmd += ["-tag:v", "hvc1"]  # lisible par les appareils Apple
        if o.son == "aucun" or not media.audio:
            cmd += ["-an"]
        elif o.son == COPIE:
            cmd += ["-c:a", "copy"]
        else:
            cmd += _args_audio(fmt.acodec, o.son)
            _filtres_audio(media, Options(normaliser=o.normaliser), cmd,
                           fmt.acodec)
        cmd += ["-sn", "-dn"]
        if fmt.muxer in ("mp4", "mov", "3gp"):
            cmd += ["-movflags", "+faststart"]

    elif cat == "anim":
        if o.fps_anim:
            filtres.append(f"fps={o.fps_anim:g}")
        if o.largeur_anim:
            filtres.append(rf"scale=w=min({o.largeur_anim}\,iw):h=-1"
                           ":flags=lanczos")
        cmd += ["-map", "0:V:0", "-an", "-sn", "-dn"]
        if fmt.cle == "gif":
            couleurs = (256, 192, 128, 64)[o.qualite]
            filtres.append(_PALETTE.format(n=couleurs, mode="diff"))
            cmd += ["-vf", ",".join(filtres), "-c:v", "gif"]
        else:
            if filtres:
                cmd += ["-vf", ",".join(filtres)]
            cmd += ["-c:v", "libwebp_anim",
                    "-quality", str((90, 80, 65, 45)[o.qualite]),
                    "-compression_level", str((2, 4, 6)[o.vitesse])]
        cmd += ["-loop", "0"]

    elif cat == "audio":
        cmd += ["-map", "0:a:0", "-vn", "-sn", "-dn"]
        cmd += _args_audio(fmt.encodeur, o.debit)
        _filtres_audio(media, o, cmd, fmt.encodeur)
        if fmt.encodeur == "libmp3lame":
            cmd += ["-id3v2_version", "3"]
        if fmt.muxer == "ipod":
            cmd += ["-movflags", "+faststart"]

    else:  # image
        if o.taille and o.taille[0] == "max":
            filtres.append(_echelle_max(o.taille[1], ":flags=lanczos"))
        elif o.taille and o.taille[0] == "pct":
            f = o.taille[1] / 100
            filtres.append(f"scale=w=max(1\\,iw*{f:g}):h=-1:flags=lanczos")
        if fmt.cle == "ico":
            filtres.append(_echelle_max(256, ":flags=lanczos"))
            filtres.append("format=rgba")  # exigé pour un PNG dans un ICO
        if fmt.cle in SANS_ALPHA and media.alpha:
            filtres.append(_SUR_BLANC)
        if fmt.cle == "gif_img":
            filtres.append(_PALETTE.format(n=256, mode="full"))
        cmd += ["-map", "0:V:0", "-an", "-sn", "-dn", "-frames:v", "1"]
        if filtres:
            cmd += ["-vf", ",".join(filtres)]
        cmd += ["-c:v", fmt.encodeur]
        q = o.qualite
        if fmt.cle == "jpg":
            cmd += ["-q:v", str((2, 3, 5, 8)[q])]
        elif fmt.cle == "webp":
            cmd += ["-quality", str((95, 85, 75, 55)[q])]
        elif fmt.cle == "avif":
            cmd += ["-still-picture", "1", "-crf", str((14, 22, 30, 40)[q]),
                    "-cpu-used", "6", "-pix_fmt", "yuv420p"]
        elif fmt.cle == "jxl":
            cmd += ["-distance", str((0.5, 1.0, 2.0, 3.5)[q])]
        elif fmt.cle == "tiff":
            cmd += ["-compression_algo", "lzw"]
        if fmt.muxer == "image2":
            cmd += ["-update", "1"]

    cmd += ["-f", fmt.muxer, str(sortie)]
    return cmd, duree


def chemin_sortie(source, ext, dossier):
    """Chemin libre dans `dossier` : « nom.ext », sinon « nom (2).ext »…"""
    source = Path(source)
    dossier = Path(dossier)
    cible = dossier / f"{source.stem}{ext}"
    n = 2
    while cible.exists():
        cible = dossier / f"{source.stem} ({n}){ext}"
        n += 1
    return cible


# --------------------------------------------------------------- exécution ---

def convertir(ffmpeg, caps, media, fmt, options, sortie, on_progress,
              stop_event):
    """Convertit `media` vers `sortie`.

    on_progress(fraction ou None, vitesse ou None) est appelé depuis ce thread.
    Lève Annule si `stop_event` est levé, RuntimeError en cas d'échec.
    """
    if (options.debut and media.duree and media.type != "image"
            and options.debut >= media.duree):
        raise RuntimeError("Le début demandé dépasse la durée du fichier.")
    cmd, duree = construire_commande(ffmpeg, caps, media, fmt, options,
                                     sortie)
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=SANS_CONSOLE)

    erreurs = deque(maxlen=20)

    def lire_erreurs():
        for ligne in proc.stderr:
            if ligne.strip():
                erreurs.append(ligne.strip())

    def surveiller():
        while proc.poll() is None:
            if stop_event.wait(0.2):
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return

    threading.Thread(target=lire_erreurs, daemon=True).start()
    threading.Thread(target=surveiller, daemon=True).start()

    vitesse = None
    for ligne in proc.stdout:
        cle, _, valeur = ligne.strip().partition("=")
        if cle == "speed":
            vitesse = valeur.strip() if valeur.strip() != "N/A" else None
        elif cle == "out_time_us" and duree:
            try:
                fait = int(valeur) / 1_000_000
            except ValueError:
                continue
            on_progress(min(max(fait / duree, 0.0), 1.0), vitesse)
    code = proc.wait()

    if stop_event.is_set():
        _supprimer(sortie)
        raise Annule()
    if code != 0 or not sortie.is_file() or sortie.stat().st_size == 0:
        _supprimer(sortie)
        raise RuntimeError(message_ffmpeg(list(erreurs)))
    return sortie


def _supprimer(chemin):
    try:
        os.remove(chemin)
    except OSError:
        pass


_BRUIT = ("nothing was written", "task finished", "terminating thread",
          "error while filtering", "could not open encoder before eof",
          "conversion failed")
_PREFIXE = re.compile(r"^(\[[^\]]*\]\s*)+")


def message_ffmpeg(lignes):
    texte = " ".join(lignes).lower()
    if "no space left" in texte:
        return "Plus d'espace disque."
    if "permission denied" in texte:
        return "Accès refusé au dossier de destination."
    if "does not contain any stream" in texte or "matches no streams" in texte:
        return "Aucune piste utilisable dans ce fichier."
    if "invalid data" in texte:
        return "Fichier endommagé ou format non pris en charge."
    if ("could not find tag for codec" in texte or "not supported" in texte
            or "error opening output file" in texte
            or "are supported for" in texte):
        return ("Ce conteneur n'accepte pas ces pistes "
                "(essayez de réencoder au lieu de copier).")
    utiles = [l for l in lignes if not any(b in l.lower() for b in _BRUIT)]
    if not utiles:
        return "La conversion a échoué."
    msg = _PREFIXE.sub("", utiles[0])
    return msg if len(msg) < 200 else msg[:197] + "…"
