"""Convertisseur — télécharge YouTube / TikTok et convertit vidéo, audio, image."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import yt_dlp

import conversion

APP_NAME = "Convertisseur"
CONFIG_FILE = Path.home() / ".convertisseur.json"

QUALITES = {
    "Maximale": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}


# ---------------------------------------------------------------- outils ---

def _base_dir():
    """Dossier des fichiers embarqués (PyInstaller) ou du script."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def trouver_ffmpeg():
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    embarque = _base_dir() / "bin" / exe
    if embarque.is_file():
        return str(embarque)
    systeme = shutil.which("ffmpeg")
    if systeme:
        return systeme
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def trouver_deno():
    """Deno sert à yt-dlp pour lire les formats YouTube haute qualité."""
    exe = "deno.exe" if os.name == "nt" else "deno"
    embarque = _base_dir() / "bin" / exe
    if embarque.is_file():
        return str(embarque)
    try:
        from deno import find_deno_bin
        return find_deno_bin()
    except Exception:
        return shutil.which("deno")


def dossier_telechargements():
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"],
                                 capture_output=True, text=True, timeout=2)
            p = Path(out.stdout.strip())
            if out.returncode == 0 and p.is_dir() and p != Path.home():
                return p
        except Exception:
            pass
    for nom in ("Downloads", "Téléchargements"):
        p = Path.home() / nom
        if p.is_dir():
            return p
    return Path.home()


def charger_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sauver_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
    except Exception:
        pass


def ouvrir_dossier(chemin):
    try:
        if os.name == "nt":
            os.startfile(chemin)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(chemin)])
        else:
            subprocess.Popen(["xdg-open", str(chemin)])
    except OSError:
        pass


def pluriel(n, mot, mots=None):
    return f"{n} {mot if n <= 1 else (mots or mot + 's')}"


# ------------------------------------------------------- téléchargement ---

Annule = conversion.Annule


def telecharger(url, format_, qualite, dossier, on_progress, stop_event):
    """Télécharge `url` et renvoie le chemin du fichier final.

    format_ : "mp3" ou "mp4" ; qualite : clé de QUALITES.
    on_progress(fraction ou None, texte) est appelé depuis ce thread.
    """
    ffmpeg = trouver_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg est introuvable. Installez-le (voir README).")

    def hook(d):
        if stop_event.is_set():
            raise Annule()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            fait = d.get("downloaded_bytes") or 0
            frac = fait / total if total else None
            vitesse = d.get("speed")
            txt = "Téléchargement…"
            if frac is not None:
                txt = f"Téléchargement… {frac * 100:.0f} %"
            if vitesse:
                txt += f"  ·  {vitesse / 1_048_576:.1f} Mo/s"
            on_progress(frac, txt)
        elif d["status"] == "finished":
            on_progress(None, "Conversion…")

    def pp_hook(d):
        if d["status"] == "started":
            on_progress(None, "Conversion…")

    opts = {
        "outtmpl": str(Path(dossier) / "%(title).150B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": ffmpeg,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "windowsfilenames": True,
        "overwrites": True,
    }

    deno = trouver_deno()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}

    if format_ == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
             "preferredquality": "320"},
            {"key": "FFmpegMetadata"},
        ]
    else:
        haut = QUALITES.get(qualite)
        tri = ["res" if haut is None else f"res:{haut}", "fps",
               "vcodec:h264", "acodec:aac"]
        opts["format"] = "bv*+ba/b"
        opts["format_sort"] = tri
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegMetadata"}]

    on_progress(None, "Analyse du lien…")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        chemin = Path(ydl.prepare_filename(info))
    chemin = chemin.with_suffix("." + format_)
    return chemin


def message_erreur(e):
    txt = str(e)
    bas = txt.lower()
    if "unsupported url" in bas:
        return "Ce lien n'est pas pris en charge."
    if "private" in bas:
        return "Cette vidéo est privée."
    if "unavailable" in bas or "not available" in bas:
        return "Cette vidéo n'est pas disponible."
    if "sign in" in bas or ("age" in bas and "confirm" in bas):
        return "Cette vidéo demande une connexion (âge ou restriction)."
    if "getaddrinfo" in bas or "network" in bas or "timed out" in bas:
        return "Pas de connexion Internet."
    txt = txt.replace("ERROR: ", "")
    return txt if len(txt) < 160 else txt[:157] + "…"


# ------------------------------------------------- choix de l'interface ---

RESOLUTIONS = {"Originale": None, "2160p (4K)": 2160, "1440p": 1440,
               "1080p": 1080, "720p": 720, "480p": 480, "360p": 360,
               "240p": 240}
IMAGES_S = {"Originale": None, "60": 60, "50": 50, "30": 30, "25": 25,
            "24": 24, "15": 15}
SON = {"320 kbit/s": 320, "256 kbit/s": 256, "192 kbit/s": 192,
       "160 kbit/s": 160, "128 kbit/s": 128, "96 kbit/s": 96,
       "Copier tel quel": conversion.COPIE, "Sans son": "aucun"}
DEBITS = {"320 kbit/s": 320, "256 kbit/s": 256, "192 kbit/s": 192,
          "160 kbit/s": 160, "128 kbit/s": 128, "96 kbit/s": 96,
          "64 kbit/s": 64}
FREQUENCES = {"Originale": None, "48 kHz": 48000, "44,1 kHz": 44100,
              "32 kHz": 32000, "24 kHz": 24000, "22,05 kHz": 22050,
              "16 kHz": 16000, "8 kHz": 8000}
CANAUX = {"Originaux": None, "Stéréo": 2, "Mono": 1}
LARGEURS = {"Originale": None, "1280 px": 1280, "960 px": 960, "800 px": 800,
            "640 px": 640, "480 px": 480, "320 px": 320, "240 px": 240}
IMAGES_S_ANIM = {"Originale": None, "30": 30, "25": 25, "20": 20, "15": 15,
                 "12": 12, "10": 10, "8": 8, "5": 5}
TAILLES = {"Originale": None, "3840 px": ("max", 3840),
           "2560 px": ("max", 2560), "1920 px": ("max", 1920),
           "1280 px": ("max", 1280), "1024 px": ("max", 1024),
           "800 px": ("max", 800), "640 px": ("max", 640),
           "512 px": ("max", 512), "256 px": ("max", 256),
           "128 px": ("max", 128), "75 %": ("pct", 75), "50 %": ("pct", 50),
           "25 %": ("pct", 25)}
QUALITES_IMAGE = ["Maximale", "Haute", "Moyenne", "Faible"]
CATEGORIES = {"video": "Vidéo", "audio": "Audio", "image": "Image"}
TYPES = {"video": "Vidéo", "audio": "Audio", "image": "Image",
         "inconnu": "?"}


def _motifs(exts):
    # Les motifs du sélecteur de fichiers Tk sont sensibles à la casse.
    return " ".join(f"*{e} *{e.upper()}" for e in sorted(exts))


# ------------------------------------------------------------ interface ---

def lancer_interface():
    import tkinter as tk
    from tkinter import ttk

    FOND = "#f6f6f4"
    TEXTE = "#1d1d1f"
    DOUX = "#77777a"
    BORD = "#d8d8d4"
    ACCENT = "#1d1d1f"
    ERREUR = "#b3261e"
    OK = "#2e7d32"

    cfg = charger_config()

    root = tk.Tk()
    root.title(APP_NAME)
    root.configure(bg=FOND)
    root.resizable(False, False)

    # Glisser-déposer (facultatif : paquet tkinterdnd2).
    try:
        from tkinterdnd2 import TkinterDnD
        TkinterDnD._require(root)
        dnd = True
    except Exception:
        dnd = False

    police = ("Segoe UI", 10) if os.name == "nt" else ("Sans", 10)
    titre_f = (police[0], 16, "bold")
    gras = (police[0], 10, "bold")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=FOND, foreground=TEXTE, font=police)
    style.configure("TFrame", background=FOND)
    style.configure("TLabel", background=FOND, foreground=TEXTE)
    style.configure("Doux.TLabel", foreground=DOUX)
    style.configure("Titre.TLabel", font=titre_f)
    style.configure("TEntry", fieldbackground="white", bordercolor=BORD,
                    lightcolor=BORD, darkcolor=BORD, padding=8)
    style.map("TEntry", bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
    style.configure("Petit.TEntry", padding=4)
    style.configure("TButton", background="white", bordercolor=BORD,
                    lightcolor="white", darkcolor="white", padding=(12, 6),
                    focuscolor=FOND)
    style.map("TButton", background=[("active", "#ececea")],
              foreground=[("disabled", "#b0b0b2")])
    style.configure("Principal.TButton", background=ACCENT, foreground="white",
                    lightcolor=ACCENT, darkcolor=ACCENT, bordercolor=ACCENT,
                    font=(police[0], 11, "bold"), padding=(12, 10))
    style.map("Principal.TButton",
              background=[("disabled", "#9a9a9c"), ("active", "#3a3a3d")],
              lightcolor=[("disabled", "#9a9a9c"), ("active", "#3a3a3d")],
              darkcolor=[("disabled", "#9a9a9c"), ("active", "#3a3a3d")],
              foreground=[("disabled", "white")])
    style.configure("Choix.TRadiobutton", background="white", padding=(0, 8),
                    anchor="center", bordercolor=BORD, indicatorsize=0,
                    font=gras)
    style.layout("Choix.TRadiobutton", [
        ("Radiobutton.border", {"sticky": "nswe", "children": [
            ("Radiobutton.padding", {"sticky": "nswe", "children": [
                ("Radiobutton.label", {"sticky": "nswe"})]})]})])
    style.map("Choix.TRadiobutton",
              background=[("selected", ACCENT), ("active", "#ececea")],
              foreground=[("selected", "white")])
    # Onglets : même forme que les choix, en plus discret.
    style.configure("Onglet.TRadiobutton", background=FOND, foreground=DOUX,
                    padding=(0, 9), anchor="center", bordercolor=BORD,
                    indicatorsize=0, font=gras)
    style.layout("Onglet.TRadiobutton", style.layout("Choix.TRadiobutton"))
    style.map("Onglet.TRadiobutton",
              background=[("selected", "white"), ("active", "#ececea")],
              foreground=[("selected", TEXTE)])
    style.configure("TCombobox", padding=5, arrowsize=14,
                    fieldbackground="white", background="white",
                    bordercolor=BORD, lightcolor="white", darkcolor="white")
    style.map("TCombobox", fieldbackground=[("readonly", "white")],
              selectbackground=[("readonly", "white")],
              selectforeground=[("readonly", TEXTE)])
    root.option_add("*TCombobox*Listbox.font", police)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    style.configure("TCheckbutton", background=FOND, indicatorbackground="white",
                    indicatorforeground=ACCENT, bordercolor=BORD,
                    focuscolor=FOND)
    style.map("TCheckbutton", background=[("active", FOND)],
              indicatorbackground=[("pressed", "#ececea")])
    style.configure("Horizontal.TProgressbar", troughcolor="#e6e6e3",
                    background=ACCENT, bordercolor="#e6e6e3",
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
    style.configure("Treeview", background="white", fieldbackground="white",
                    bordercolor=BORD, lightcolor=BORD, darkcolor=BORD,
                    rowheight=26)
    style.map("Treeview", background=[("selected", "#e8e8e5")],
              foreground=[("selected", TEXTE)])
    style.configure("Treeview.Heading", background=FOND, foreground=DOUX,
                    bordercolor=BORD, lightcolor=FOND, darkcolor=FOND,
                    relief="flat", font=(police[0], 9, "bold"), padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", FOND)])
    style.configure("Vertical.TScrollbar", background="white",
                    troughcolor=FOND, bordercolor=BORD, lightcolor="white",
                    darkcolor="white", arrowcolor=DOUX)

    principal = ttk.Frame(root, padding=(24, 20))
    principal.pack(fill="both", expand=True)
    principal.columnconfigure(0, weight=1)

    ttk.Label(principal, text=APP_NAME, style="Titre.TLabel").grid(
        row=0, column=0, sticky="w")
    sous_titre = ttk.Label(principal, style="Doux.TLabel")
    sous_titre.grid(row=1, column=0, sticky="w", pady=(0, 12))

    onglet_var = tk.StringVar(value=cfg.get("onglet", "telecharger"))
    barre_onglets = ttk.Frame(principal)
    barre_onglets.grid(row=2, column=0, sticky="ew", pady=(0, 16))
    barre_onglets.columnconfigure((0, 1), weight=1, uniform="o")
    for i, (cle, texte) in enumerate((("telecharger", "Télécharger"),
                                      ("convertir", "Convertir des fichiers"))):
        ttk.Radiobutton(barre_onglets, text=texte, value=cle,
                        variable=onglet_var, style="Onglet.TRadiobutton",
                        takefocus=False).grid(row=0, column=i, sticky="ew")

    ctx = {
        "tk": tk, "ttk": ttk, "root": root, "cfg": cfg, "police": police,
        "dnd": dnd, "FOND": FOND, "TEXTE": TEXTE, "DOUX": DOUX,
        "ERREUR": ERREUR, "OK": OK, "BORD": BORD,
    }
    onglets = {
        "telecharger": (onglet_telechargement(principal, ctx),
                        "YouTube et TikTok vers MP3 ou MP4"),
        "convertir": (onglet_conversion(principal, ctx),
                      "Vidéos, musiques et images : tous les formats courants"),
    }

    def changer_onglet(*_):
        actif = onglet_var.get()
        if actif not in onglets:
            actif = "telecharger"
            onglet_var.set(actif)
        for cle, (cadre, texte) in onglets.items():
            if cle == actif:
                cadre.grid(row=3, column=0, sticky="nsew")
                sous_titre.configure(text=texte)
                cadre.focus_initial()
            else:
                cadre.grid_remove()
        cfg["onglet"] = actif
        sauver_config(cfg)

    onglet_var.trace_add("write", changer_onglet)
    changer_onglet()
    root.mainloop()


def _ligne_statut(parent, ctx, texte, marge=150):
    """Libellé d'état dont le retour à la ligne suit la largeur."""
    tk = ctx["tk"]
    statut = tk.Label(parent, text=texte, bg=ctx["FOND"], fg=ctx["DOUX"],
                      font=ctx["police"], anchor="w", justify="left",
                      wraplength=330)
    statut.pack(side="left", fill="x", expand=True)
    parent.bind("<Configure>", lambda e: statut.configure(
        wraplength=max(e.width - marge, 200)))
    return statut


# ------------------------------------------------- onglet téléchargement ---

def onglet_telechargement(parent, ctx):
    tk, ttk, root, cfg = ctx["tk"], ctx["ttk"], ctx["root"], ctx["cfg"]
    from tkinter import filedialog
    DOUX, ERREUR, OK = ctx["DOUX"], ctx["ERREUR"], ctx["OK"]

    dossier = Path(cfg.get("dossier") or dossier_telechargements())
    if not dossier.is_dir():
        dossier = dossier_telechargements()

    cadre = ttk.Frame(parent)
    cadre.columnconfigure(0, weight=1)

    # Lien
    ligne_url = ttk.Frame(cadre)
    ligne_url.grid(row=0, column=0, sticky="ew")
    ligne_url.columnconfigure(0, weight=1)
    url_var = tk.StringVar()
    champ = ttk.Entry(ligne_url, textvariable=url_var, width=48)
    champ.grid(row=0, column=0, sticky="ew", padx=(0, 8))

    def coller():
        try:
            url_var.set(root.clipboard_get().strip())
        except tk.TclError:
            pass
        champ.icursor("end")

    ttk.Button(ligne_url, text="Coller", command=coller).grid(row=0, column=1)

    if ctx["dnd"]:
        from tkinterdnd2 import DND_TEXT

        def deposer_lien(e):
            url_var.set(e.data.strip().splitlines()[0] if e.data else "")
            return e.action

        champ.drop_target_register(DND_TEXT)
        champ.dnd_bind("<<Drop>>", deposer_lien)

    # Format
    format_var = tk.StringVar(value=cfg.get("format", "mp3"))
    ligne_fmt = ttk.Frame(cadre)
    ligne_fmt.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    ligne_fmt.columnconfigure((0, 1), weight=1, uniform="f")
    ttk.Radiobutton(ligne_fmt, text="MP3  ·  Audio", value="mp3",
                    variable=format_var, style="Choix.TRadiobutton",
                    takefocus=False).grid(row=0, column=0, sticky="ew")
    ttk.Radiobutton(ligne_fmt, text="MP4  ·  Vidéo", value="mp4",
                    variable=format_var, style="Choix.TRadiobutton",
                    takefocus=False).grid(row=0, column=1, sticky="ew")

    # Qualité (vidéo seulement)
    ligne_q = ttk.Frame(cadre)
    ligne_q.grid(row=2, column=0, sticky="ew", pady=(12, 0))
    ttk.Label(ligne_q, text="Qualité vidéo").pack(side="left")
    qualite_var = tk.StringVar(value=cfg.get("qualite", "Maximale"))
    combo = ttk.Combobox(ligne_q, textvariable=qualite_var, width=12,
                         values=list(QUALITES), state="readonly")
    combo.pack(side="right")
    note_q = ttk.Label(ligne_q, text="MP3 320 kbit/s", style="Doux.TLabel")

    def maj_format(*_):
        if format_var.get() == "mp4":
            note_q.pack_forget()
            combo.pack(side="right")
        else:
            combo.pack_forget()
            note_q.pack(side="right")

    format_var.trace_add("write", maj_format)
    maj_format()

    # Dossier
    ligne_d = ttk.Frame(cadre)
    ligne_d.grid(row=3, column=0, sticky="ew", pady=(12, 0))
    ligne_d.columnconfigure(0, weight=1)
    dossier_var = tk.StringVar(value=str(dossier))
    ttk.Label(ligne_d, textvariable=dossier_var, style="Doux.TLabel",
              width=44).grid(row=0, column=0, sticky="w")

    def choisir_dossier():
        d = filedialog.askdirectory(initialdir=dossier_var.get(),
                                    title="Dossier d'enregistrement")
        if d:
            dossier_var.set(d)

    ttk.Button(ligne_d, text="Changer", command=choisir_dossier).grid(
        row=0, column=1)

    # Action
    bouton = ttk.Button(cadre, text="Télécharger", style="Principal.TButton")
    bouton.grid(row=4, column=0, sticky="ew", pady=(20, 12))

    barre = ttk.Progressbar(cadre, mode="determinate", maximum=1.0)
    barre.grid(row=5, column=0, sticky="ew")

    ligne_s = ttk.Frame(cadre)
    ligne_s.grid(row=6, column=0, sticky="ew", pady=(8, 0))
    statut = _ligne_statut(ligne_s, ctx, "Collez un lien pour commencer.")
    bouton_ouvrir = ttk.Button(ligne_s, text="Ouvrir le dossier",
                               command=lambda: ouvrir_dossier(
                                   dossier_var.get()))

    # Logique
    events = queue.Queue()
    stop_event = threading.Event()
    en_cours = {"actif": False}

    def afficher(texte, couleur=DOUX):
        statut.configure(text=texte, fg=couleur)

    def demarrer(*_):
        if en_cours["actif"]:
            stop_event.set()
            bouton.configure(state="disabled")
            afficher("Annulation…")
            return
        url = url_var.get().strip()
        if not url.startswith(("http://", "https://")):
            afficher("Ce lien ne semble pas valide.", ERREUR)
            champ.focus_set()
            return
        cfg.update(dossier=dossier_var.get(), format=format_var.get(),
                   qualite=qualite_var.get())
        sauver_config(cfg)

        stop_event.clear()
        en_cours["actif"] = True
        bouton.configure(text="Annuler")
        bouton_ouvrir.pack_forget()
        barre.configure(mode="indeterminate")
        barre.start(12)

        def travail():
            try:
                f = telecharger(url, format_var.get(), qualite_var.get(),
                                dossier_var.get(),
                                lambda fr, t: events.put(("prog", fr, t)),
                                stop_event)
                events.put(("ok", f))
            except Exception as e:  # noqa: BLE001
                if stop_event.is_set() or isinstance(e, Annule):
                    events.put(("annule",))
                else:
                    events.put(("err", e))

        threading.Thread(target=travail, daemon=True).start()

    def fin():
        en_cours["actif"] = False
        barre.stop()
        bouton.configure(text="Télécharger", state="normal")

    def lire_events():
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == "prog":
                    _, frac, texte = ev
                    if frac is None:
                        if str(barre.cget("mode")) != "indeterminate":
                            barre.configure(mode="indeterminate")
                            barre.start(12)
                    else:
                        if str(barre.cget("mode")) != "determinate":
                            barre.stop()
                            barre.configure(mode="determinate")
                        barre["value"] = frac
                    afficher(texte)
                elif ev[0] == "ok":
                    fin()
                    barre.configure(mode="determinate")
                    barre["value"] = 1.0
                    afficher(f"Terminé : {ev[1].name}", OK)
                    bouton_ouvrir.pack(side="right")
                    url_var.set("")
                elif ev[0] == "annule":
                    fin()
                    barre.configure(mode="determinate")
                    barre["value"] = 0
                    afficher("Téléchargement annulé.")
                elif ev[0] == "err":
                    fin()
                    barre.configure(mode="determinate")
                    barre["value"] = 0
                    afficher(message_erreur(ev[1]), ERREUR)
        except queue.Empty:
            pass
        root.after(100, lire_events)

    bouton.configure(command=demarrer)
    champ.bind("<Return>", demarrer)
    root.after(100, lire_events)
    cadre.focus_initial = champ.focus_set
    return cadre


# ---------------------------------------------------- onglet conversion ---

def onglet_conversion(parent, ctx):
    tk, ttk, root, cfg = ctx["tk"], ctx["ttk"], ctx["root"], ctx["cfg"]
    from tkinter import filedialog
    DOUX, ERREUR, OK, TEXTE = ctx["DOUX"], ctx["ERREUR"], ctx["OK"], ctx["TEXTE"]
    police = ctx["police"]
    C = conversion

    ccfg = cfg.setdefault("conversion", {})
    ffmpeg = trouver_ffmpeg()
    caps = C.Capacites(ffmpeg) if ffmpeg else None
    formats = caps.formats() if caps else []
    par_categorie = {
        "video": [f for f in formats if f.categorie in ("video", "anim")],
        "audio": [f for f in formats if f.categorie == "audio"],
        "image": [f for f in formats if f.categorie == "image"],
    }

    cadre = ttk.Frame(parent)
    cadre.columnconfigure(0, weight=1, minsize=600)

    # ---- Liste des fichiers
    outils = ttk.Frame(cadre)
    outils.grid(row=0, column=0, sticky="ew")
    b_fichiers = ttk.Button(outils, text="Ajouter des fichiers")
    b_fichiers.pack(side="left")
    b_dossier = ttk.Button(outils, text="Ajouter un dossier")
    b_dossier.pack(side="left", padx=(8, 0))
    b_vider = ttk.Button(outils, text="Vider")
    b_vider.pack(side="right")
    b_retirer = ttk.Button(outils, text="Retirer")
    b_retirer.pack(side="right", padx=(0, 8))
    boutons_liste = (b_fichiers, b_dossier, b_vider, b_retirer)

    cadre_liste = ttk.Frame(cadre)
    cadre_liste.grid(row=1, column=0, sticky="ew", pady=(10, 0))
    cadre_liste.columnconfigure(0, weight=1)
    arbre = ttk.Treeview(cadre_liste, columns=("nom", "type", "infos", "etat"),
                         show="headings", height=5, selectmode="extended")
    for col, titre, larg, ext in (("nom", "Fichier", 230, True),
                                  ("type", "Type", 62, False),
                                  ("infos", "Infos", 150, False),
                                  ("etat", "État", 100, False)):
        arbre.heading(col, text=titre, anchor="w")
        arbre.column(col, width=larg, minwidth=50, stretch=ext, anchor="w")
    arbre.tag_configure("ok", foreground=OK)
    arbre.tag_configure("err", foreground=ERREUR)
    arbre.tag_configure("ign", foreground=DOUX)
    arbre.tag_configure("cours", foreground=TEXTE)
    defil = ttk.Scrollbar(cadre_liste, orient="vertical", command=arbre.yview)
    arbre.configure(yscrollcommand=defil.set)
    arbre.grid(row=0, column=0, sticky="ew")
    defil.grid(row=0, column=1, sticky="ns")

    texte_vide = ("Glissez vos fichiers ici\nou cliquez sur « Ajouter des "
                  "fichiers »" if ctx["dnd"] else
                  "Cliquez sur « Ajouter des fichiers »\n"
                  "pour choisir des vidéos, musiques ou images")
    vide = tk.Label(cadre_liste, text=texte_vide, bg="white", fg=DOUX,
                    font=police, justify="center", cursor="hand2")

    # ---- Catégorie et format
    cat_var = tk.StringVar(value=ccfg.get("categorie", "video"))
    if cat_var.get() not in CATEGORIES:
        cat_var.set("video")
    ligne_cat = ttk.Frame(cadre)
    ligne_cat.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    ligne_cat.columnconfigure((0, 1, 2), weight=1, uniform="c")
    for i, (cle, nom) in enumerate(CATEGORIES.items()):
        ttk.Radiobutton(ligne_cat, text=f"Vers {nom.lower()}", value=cle,
                        variable=cat_var, style="Choix.TRadiobutton",
                        takefocus=False).grid(row=0, column=i, sticky="ew")

    ligne_fmt = ttk.Frame(cadre)
    ligne_fmt.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    ligne_fmt.columnconfigure(1, weight=1)
    ttk.Label(ligne_fmt, text="Format", font=(police[0], 10, "bold")).grid(
        row=0, column=0, sticky="w", padx=(0, 12))
    format_var = tk.StringVar()
    combo_fmt = ttk.Combobox(ligne_fmt, textvariable=format_var,
                             state="readonly", height=16)
    combo_fmt.grid(row=0, column=1, sticky="ew")

    # ---- Options (grille de 2 colonnes, réarrangée selon le format)
    opts = ttk.Frame(cadre)
    opts.grid(row=4, column=0, sticky="ew", pady=(6, 0))
    opts.columnconfigure((1, 3), weight=1, uniform="o")
    opts.columnconfigure(0, minsize=96)
    opts.columnconfigure(2, minsize=96)
    for r in range(4):  # hauteur fixe : la fenêtre ne saute pas
        opts.rowconfigure(r, minsize=34)
    champs = {}

    def var(nom, defaut, valeurs=None):
        v = ccfg.get(nom, defaut)
        if valeurs is not None and v not in valeurs:
            v = defaut
        return tk.StringVar(value=v)

    def combo(nom, texte, variable, valeurs):
        lab = ttk.Label(opts, text=texte)
        cb = ttk.Combobox(opts, textvariable=variable, values=list(valeurs),
                          state="readonly", width=16, height=14)
        champs[nom] = (lab, cb)
        return cb

    v = {
        "vcodec": tk.StringVar(),
        "qualite_v": var("qualite_v", "Haute", C.QUALITES),
        "resolution": var("resolution", "Originale", RESOLUTIONS),
        "fps": var("fps", "Originale", IMAGES_S),
        "vitesse": var("vitesse", "Normale", C.VITESSES),
        "son": var("son", "192 kbit/s", SON),
        "largeur": var("largeur", "480 px", LARGEURS),
        "fps_anim": var("fps_anim", "15", IMAGES_S_ANIM),
        "qualite_a": var("qualite_a", "Haute", C.QUALITES),
        "debit": var("debit", "320 kbit/s", DEBITS),
        "frequence": var("frequence", "Originale", FREQUENCES),
        "canaux": var("canaux", "Originaux", CANAUX),
        "qualite_i": var("qualite_i", "Haute", QUALITES_IMAGE),
        "taille": var("taille", "Originale", TAILLES),
        "rotation": var("rotation", "Aucune", C.ROTATIONS),
    }
    cb_vcodec = combo("vcodec", "Codec vidéo", v["vcodec"], [])
    combo("qualite_v", "Qualité", v["qualite_v"], C.QUALITES)
    combo("resolution", "Résolution", v["resolution"], RESOLUTIONS)
    combo("fps", "Images/s", v["fps"], IMAGES_S)
    combo("vitesse", "Encodage", v["vitesse"], C.VITESSES)
    combo("son", "Son", v["son"], SON)
    combo("largeur", "Largeur", v["largeur"], LARGEURS)
    combo("fps_anim", "Images/s", v["fps_anim"], IMAGES_S_ANIM)
    combo("qualite_a", "Qualité", v["qualite_a"], C.QUALITES)
    combo("debit", "Débit", v["debit"], DEBITS)
    cb_freq = combo("frequence", "Fréquence", v["frequence"], FREQUENCES)
    combo("canaux", "Canaux", v["canaux"], CANAUX)
    combo("qualite_i", "Qualité", v["qualite_i"], QUALITES_IMAGE)
    combo("taille", "Taille max", v["taille"], TAILLES)
    combo("rotation", "Rotation", v["rotation"], C.ROTATIONS)
    note_opts = ttk.Label(opts, style="Doux.TLabel")

    # ---- Découpe / capture et volume
    ligne_t = ttk.Frame(cadre)
    ligne_t.grid(row=5, column=0, sticky="ew", pady=(6, 0))
    lab_debut = ttk.Label(ligne_t, text="Découper de")
    lab_debut.pack(side="left")
    debut_var = tk.StringVar()
    fin_var = tk.StringVar()
    e_debut = ttk.Entry(ligne_t, textvariable=debut_var, width=9,
                        style="Petit.TEntry")
    e_debut.pack(side="left", padx=(8, 0))
    lab_a = ttk.Label(ligne_t, text="à")
    e_fin = ttk.Entry(ligne_t, textvariable=fin_var, width=9,
                      style="Petit.TEntry")
    note_t = ttk.Label(ligne_t, text="ex. 1:30", style="Doux.TLabel")
    norm_var = tk.BooleanVar(value=bool(ccfg.get("normaliser", False)))
    case_norm = ttk.Checkbutton(ligne_t, text="Normaliser le volume",
                                variable=norm_var, takefocus=False)

    # ---- Destination
    ligne_d = ttk.Frame(cadre)
    ligne_d.grid(row=6, column=0, sticky="ew", pady=(10, 0))
    ligne_d.columnconfigure(1, weight=1)
    a_cote_var = tk.BooleanVar(value=bool(ccfg.get("a_cote", False)))
    ttk.Checkbutton(ligne_d, text="À côté des originaux", variable=a_cote_var,
                    takefocus=False).grid(row=0, column=0, sticky="w",
                                          padx=(0, 12))
    dossier = Path(ccfg.get("dossier") or cfg.get("dossier")
                   or dossier_telechargements())
    if not dossier.is_dir():
        dossier = dossier_telechargements()
    dossier_var = tk.StringVar(value=str(dossier))
    lab_dossier = ttk.Label(ligne_d, textvariable=dossier_var,
                            style="Doux.TLabel", width=30)
    lab_dossier.grid(row=0, column=1, sticky="ew")

    def choisir_dossier():
        d = filedialog.askdirectory(initialdir=dossier_var.get(),
                                    title="Dossier des fichiers convertis")
        if d:
            dossier_var.set(d)
            a_cote_var.set(False)

    b_changer = ttk.Button(ligne_d, text="Changer", command=choisir_dossier)
    b_changer.grid(row=0, column=2)

    def maj_destination(*_):
        if a_cote_var.get():
            lab_dossier.configure(foreground="#b0b0b2")
        else:
            lab_dossier.configure(foreground=DOUX)

    a_cote_var.trace_add("write", maj_destination)
    maj_destination()

    # ---- Action et progression
    bouton = ttk.Button(cadre, text="Convertir", style="Principal.TButton")
    bouton.grid(row=7, column=0, sticky="ew", pady=(16, 10))
    barre = ttk.Progressbar(cadre, mode="determinate", maximum=1.0)
    barre.grid(row=8, column=0, sticky="ew")
    ligne_s = ttk.Frame(cadre)
    ligne_s.grid(row=9, column=0, sticky="ew", pady=(8, 0))
    statut = _ligne_statut(ligne_s, ctx, "")
    dernier = {"dossier": None}
    bouton_ouvrir = ttk.Button(ligne_s, text="Ouvrir le dossier",
                               command=lambda: ouvrir_dossier(
                                   dernier["dossier"]))

    def afficher(texte, couleur=DOUX):
        statut.configure(text=texte, fg=couleur)

    # ================================================== logique : format
    def fmt_courant():
        for f in par_categorie[cat_var.get()]:
            if f.libelle == format_var.get():
                return f
        return None

    def maj_categorie(*_):
        cat = cat_var.get()
        liste = par_categorie[cat]
        combo_fmt.configure(values=[f.libelle for f in liste])
        voulu = ccfg.get(f"format_{cat}")
        choix = next((f for f in liste if f.cle == voulu),
                     liste[0] if liste else None)
        format_var.set(choix.libelle if choix else "")

    def maj_format(*_):
        f = fmt_courant()
        if f is None:
            disposer([])
            return
        ccfg[f"format_{cat_var.get()}"] = f.cle
        if f.categorie == "video":
            noms = [C.CODECS_VIDEO[c][0] for c in caps.codecs_video(f)]
            noms.append(C.NOM_COPIE)
            cb_vcodec.configure(values=noms)
            code = ccfg.get(f"vcodec_{f.cle}")
            voulu = (C.NOM_COPIE if code == C.COPIE
                     else C.CODECS_VIDEO.get(code, ("",))[0])
            if voulu in noms:
                v["vcodec"].set(voulu)
            elif v["vcodec"].get() not in noms:
                v["vcodec"].set(noms[0])
        if f.categorie == "audio":
            libres = [k for k, hz in FREQUENCES.items()
                      if hz is None or not f.frequences or hz in f.frequences]
            cb_freq.configure(values=libres)
            if v["frequence"].get() not in libres:
                v["frequence"].set("Originale")
        maj_options()

    def code_vcodec():
        nom = v["vcodec"].get()
        if nom == C.NOM_COPIE:
            return C.COPIE
        return next((c for c, (n, _) in C.CODECS_VIDEO.items() if n == nom),
                    "h264")

    def maj_options(*_):
        f = fmt_courant()
        if f is None:
            disposer([])
            return
        cat = f.categorie
        note = ""
        if cat == "video":
            code = code_vcodec()
            ccfg[f"vcodec_{f.cle}"] = code
            if code == C.COPIE:
                noms = ["vcodec", "son"]
                note = "Rapide et sans perte, si le format l'accepte."
            else:
                noms = ["vcodec", "qualite_v", "resolution", "fps"]
                if caps.encodeur_video(code) in C.AVEC_VITESSE:
                    noms.append("vitesse")
                noms += ["son", "rotation"]
        elif cat == "anim":
            noms = ["largeur", "fps_anim", "qualite_a", "rotation"]
            if f.cle == "webp_anim":
                noms.append("vitesse")
        elif cat == "audio":
            noms = (["debit"] if f.avec_perte else []) + ["frequence",
                                                          "canaux"]
            if not f.avec_perte:
                note = "Sans perte : la qualité d'origine est conservée."
        else:
            noms = (["qualite_i"] if f.avec_perte else []) + ["taille",
                                                              "rotation"]
            if f.cle == "ico":
                note = "Les icônes sont limitées à 256 px."
        disposer(noms, note)

        # Ligne découpe / capture
        for w in (lab_a, e_fin, note_t, case_norm):
            w.pack_forget()
        if cat == "image":
            lab_debut.configure(text="Capture des vidéos à")
            note_t.configure(text="ex. 0:12 (vide = début)")
            note_t.pack(side="left", padx=(8, 0))
        else:
            lab_debut.configure(text="Découper de")
            note_t.configure(text="ex. 1:30")
            lab_a.pack(side="left", padx=8)
            e_fin.pack(side="left")
            note_t.pack(side="left", padx=(8, 0))
            if cat in ("video", "audio"):
                case_norm.pack(side="right")

    def disposer(noms, note=""):
        for lab, w in champs.values():
            lab.grid_remove()
            w.grid_remove()
        note_opts.grid_remove()
        i = 0
        for i, nom in enumerate(noms):
            r, c = divmod(i, 2)
            lab, w = champs[nom]
            lab.grid(row=r, column=c * 2, sticky="w",
                     padx=(0 if c == 0 else 18, 10), pady=2)
            w.grid(row=r, column=c * 2 + 1, sticky="ew", pady=2)
        if note:
            r = (len(noms) + 1) // 2
            note_opts.configure(text=note)
            note_opts.grid(row=r, column=0, columnspan=4, sticky="w", pady=3)

    cat_var.trace_add("write", maj_categorie)
    format_var.trace_add("write", maj_format)
    v["vcodec"].trace_add("write", maj_options)

    # ================================================== logique : liste
    fichiers = {}          # iid -> {"chemin", "media", "detail", "sortie"}
    events = queue.Queue()
    a_analyser = queue.Queue()
    stop_event = threading.Event()
    etat = {"actif": False}

    def analyseur():
        while True:
            iid, chemin = a_analyser.get()
            events.put(("media", iid, C.analyser(ffmpeg, chemin)))

    if ffmpeg:
        threading.Thread(target=analyseur, daemon=True).start()

    def maj_vide():
        if arbre.get_children():
            vide.place_forget()
        else:
            vide.place(relx=0.5, rely=0.55, anchor="center")

    def ajouter(chemins):
        if etat["actif"]:
            return
        connus = {str(f["chemin"]) for f in fichiers.values()}
        nouveaux = []
        for c in chemins:
            c = Path(c)
            if c.is_dir():
                nouveaux += sorted(
                    p for p in c.rglob("*")
                    if p.is_file() and p.suffix.lower() in C.EXT_MEDIAS)
            elif c.is_file():
                nouveaux.append(c)
        ajoutes = 0
        for c in nouveaux:
            if str(c) in connus:
                continue
            connus.add(str(c))
            iid = arbre.insert("", "end", values=(c.name, "…", "",
                                                  "En attente"))
            fichiers[iid] = {"chemin": c, "media": None, "detail": None,
                             "sortie": None}
            if ffmpeg:
                a_analyser.put((iid, c))
            ajoutes += 1
        maj_vide()
        if nouveaux and not ajoutes:
            afficher("Ces fichiers sont déjà dans la liste.")
        elif ajoutes:
            total = len(fichiers)
            afficher(f"{pluriel(total, 'fichier')} dans la liste.")
        elif chemins:
            afficher("Aucun fichier vidéo, audio ou image trouvé ici.")

    def choisir_fichiers():
        types = [("Vidéos, musiques et images", _motifs(C.EXT_MEDIAS)),
                 ("Vidéos", _motifs(C.EXT_VIDEO)),
                 ("Musiques", _motifs(C.EXT_AUDIO)),
                 ("Images", _motifs(C.EXT_IMAGE)),
                 ("Tous les fichiers", "*")]
        noms = filedialog.askopenfilenames(
            title="Fichiers à convertir", filetypes=types,
            initialdir=ccfg.get("source") or str(Path.home()))
        if noms:
            ccfg["source"] = str(Path(noms[0]).parent)
            ajouter(noms)

    def choisir_dossier_source():
        d = filedialog.askdirectory(
            title="Dossier à convertir (sous-dossiers inclus)",
            initialdir=ccfg.get("source") or str(Path.home()))
        if d:
            ccfg["source"] = d
            ajouter([d])

    def retirer(*_):
        if etat["actif"]:
            return
        for iid in arbre.selection():
            arbre.delete(iid)
            fichiers.pop(iid, None)
        maj_vide()

    def vider():
        if etat["actif"]:
            return
        arbre.delete(*arbre.get_children())
        fichiers.clear()
        maj_vide()
        afficher("")

    def selection(*_):
        sel = arbre.selection()
        if len(sel) != 1 or etat["actif"]:
            return
        f = fichiers.get(sel[0])
        if not f:
            return
        if f["sortie"]:
            afficher(f"Converti : {f['sortie'].name}", OK)
        elif f["detail"]:
            afficher(f"{f['chemin'].name} : {f['detail']}", ERREUR)
        else:
            afficher(str(f["chemin"]))

    def double_clic(e):
        iid = arbre.identify_row(e.y)
        f = fichiers.get(iid)
        if f:
            ouvrir_dossier((f["sortie"] or f["chemin"]).parent)

    b_fichiers.configure(command=choisir_fichiers)
    b_dossier.configure(command=choisir_dossier_source)
    b_retirer.configure(command=retirer)
    b_vider.configure(command=vider)
    arbre.bind("<Delete>", retirer)
    arbre.bind("<BackSpace>", retirer)
    arbre.bind("<<TreeviewSelect>>", selection)
    arbre.bind("<Double-1>", double_clic)
    vide.bind("<Button-1>", lambda e: choisir_fichiers())

    if ctx["dnd"]:
        from tkinterdnd2 import DND_FILES

        def deposer(e):
            ajouter(root.tk.splitlist(e.data))
            return e.action

        for w in (arbre, vide, cadre):
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", deposer)

    # ================================================== logique : conversion
    def lire_options(f):
        o = C.Options(rotation=v["rotation"].get())
        cat = f.categorie
        if cat == "video":
            o.vcodec = code_vcodec()
            o.qualite = C.QUALITES.index(v["qualite_v"].get())
            o.hauteur = RESOLUTIONS[v["resolution"].get()]
            o.fps = IMAGES_S[v["fps"].get()]
            o.vitesse = C.VITESSES.index(v["vitesse"].get())
            o.son = SON[v["son"].get()]
        elif cat == "anim":
            o.largeur_anim = LARGEURS[v["largeur"].get()]
            o.fps_anim = IMAGES_S_ANIM[v["fps_anim"].get()]
            o.qualite = C.QUALITES.index(v["qualite_a"].get())
            o.vitesse = C.VITESSES.index(v["vitesse"].get())
        elif cat == "audio":
            o.debit = DEBITS[v["debit"].get()]
            o.frequence = FREQUENCES[v["frequence"].get()]
            o.canaux = CANAUX[v["canaux"].get()]
        else:
            o.qualite = QUALITES_IMAGE.index(v["qualite_i"].get())
            o.taille = TAILLES[v["taille"].get()]
        o.normaliser = cat in ("video", "audio") and norm_var.get()
        try:
            o.debut = C.lire_temps(debut_var.get())
        except ValueError:
            raise ValueError("Le moment de début n'est pas valide "
                             "(ex. 90, 1:30 ou 0:01:30).") from None
        if cat != "image":
            try:
                o.fin = C.lire_temps(fin_var.get())
            except ValueError:
                raise ValueError("Le moment de fin n'est pas valide "
                                 "(ex. 90, 1:30 ou 0:01:30).") from None
            if o.fin is not None and o.fin <= (o.debut or 0):
                raise ValueError("La fin doit être après le début.")
        return o

    def demarrer(*_):
        if etat["actif"]:
            stop_event.set()
            bouton.configure(state="disabled")
            afficher("Annulation…")
            return
        if not ffmpeg:
            afficher("FFmpeg est introuvable. Installez-le (voir README).",
                     ERREUR)
            return
        if not fichiers:
            afficher("Ajoutez d'abord des fichiers à convertir.", ERREUR)
            return
        f = fmt_courant()
        if f is None:
            afficher("Choisissez un format de sortie.", ERREUR)
            return
        try:
            o = lire_options(f)
        except ValueError as e:
            afficher(str(e), ERREUR)
            return
        destination = None if a_cote_var.get() else Path(dossier_var.get())
        if destination and not destination.is_dir():
            afficher("Le dossier de destination n'existe plus.", ERREUR)
            return

        ccfg.update({k: var_.get() for k, var_ in v.items()
                     if k != "vcodec"})
        ccfg.update(categorie=cat_var.get(), normaliser=norm_var.get(),
                    a_cote=a_cote_var.get(), dossier=dossier_var.get())
        sauver_config(cfg)

        taches = [(iid, fichiers[iid]["chemin"], fichiers[iid]["media"])
                  for iid in arbre.get_children()]
        for iid, _, _ in taches:
            fichiers[iid].update(detail=None, sortie=None)
            arbre.set(iid, "etat", "En attente")
            arbre.item(iid, tags=())
        stop_event.clear()
        etat["actif"] = True
        bouton.configure(text="Annuler")
        bouton_ouvrir.pack_forget()
        for b in boutons_liste:
            b.configure(state="disabled")
        barre.configure(mode="determinate")
        barre["value"] = 0
        threading.Thread(target=travail, args=(taches, f, o, destination),
                         daemon=True).start()

    def travail(taches, f, o, destination):
        n = len(taches)
        bilan = {"ok": 0, "err": 0, "ign": 0, "annule": False}
        dossier_fin = None
        for i, (iid, chemin, media) in enumerate(taches):
            if stop_event.is_set():
                bilan["annule"] = True
                break
            if media is None:
                media = C.analyser(ffmpeg, chemin)
                events.put(("media", iid, media))
            raison = C.incompatibilite(media, f)
            if raison:
                bilan["ign"] += 1
                illisible = bool(media.erreur) or media.type == "inconnu"
                events.put(("etat", iid, "Illisible" if illisible
                            else "Ignoré", "err" if illisible else "ign",
                            raison, None))
                continue
            dossier = destination or chemin.parent
            nom = chemin.name
            debut_txt = f"{i + 1}/{n}  ·  {nom}"

            def prog(frac, vitesse, i=i, iid=iid, debut_txt=debut_txt):
                txt = f"{debut_txt}  ·  {frac * 100:.0f} %"
                if vitesse:
                    txt += f"  ·  {vitesse}"
                events.put(("prog", iid, frac, (i + frac) / n, txt))

            events.put(("etat", iid, "En cours…", "cours", None, None))
            events.put(("prog", iid, None, i / n, debut_txt))
            try:
                sortie = C.chemin_sortie(chemin, f.ext, dossier)
                C.convertir(ffmpeg, caps, media, f, o, sortie, prog,
                            stop_event)
                bilan["ok"] += 1
                dossier_fin = sortie.parent
                events.put(("etat", iid, "Terminé", "ok", None, sortie))
            except C.Annule:
                bilan["annule"] = True
                events.put(("etat", iid, "Annulé", "ign", None, None))
                break
            except Exception as e:  # noqa: BLE001
                bilan["err"] += 1
                events.put(("etat", iid, "Erreur", "err", str(e), None))
        events.put(("fin", bilan, dossier_fin))

    def fin(bilan, dossier_fin):
        etat["actif"] = False
        bouton.configure(text="Convertir", state="normal")
        for b in boutons_liste:
            b.configure(state="normal")
        ok, err, ign = bilan["ok"], bilan["err"], bilan["ign"]
        if bilan["annule"]:
            barre["value"] = 0
            txt = "Conversion annulée."
            if ok:
                txt += f"  {pluriel(ok, 'fichier converti', 'fichiers convertis')}."
            afficher(txt)
        else:
            barre["value"] = 1.0
            morceaux = []
            if ok:
                morceaux.append(pluriel(ok, "fichier converti",
                                        "fichiers convertis"))
            if err:
                morceaux.append(pluriel(err, "erreur"))
            if ign:
                morceaux.append(pluriel(ign, "ignoré", "ignorés"))
            txt = ", ".join(morceaux) + "."
            if err or ign:
                txt += "  Sélectionnez une ligne pour le détail."
            afficher(txt[0].upper() + txt[1:],
                     OK if ok and not err else (ERREUR if err else DOUX))
        if dossier_fin:
            dernier["dossier"] = dossier_fin
            bouton_ouvrir.pack(side="right")

    def lire_events():
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == "media":
                    _, iid, m = ev
                    if iid not in fichiers:
                        continue
                    fichiers[iid]["media"] = m
                    arbre.set(iid, "type", TYPES[m.type])
                    arbre.set(iid, "infos", m.resume())
                    if m.erreur and not etat["actif"]:
                        fichiers[iid]["detail"] = m.erreur
                        arbre.set(iid, "etat", "Illisible")
                        arbre.item(iid, tags=("err",))
                elif ev[0] == "etat":
                    _, iid, texte, tag, detail, sortie = ev
                    if iid in fichiers:
                        fichiers[iid].update(detail=detail, sortie=sortie)
                        arbre.set(iid, "etat", texte)
                        arbre.item(iid, tags=(tag,))
                        if tag == "cours":
                            arbre.see(iid)
                elif ev[0] == "prog":
                    _, iid, frac, total, texte = ev
                    barre["value"] = total
                    if frac is not None and iid in fichiers:
                        arbre.set(iid, "etat", f"{frac * 100:.0f} %")
                    afficher(texte)
                elif ev[0] == "fin":
                    fin(ev[1], ev[2])
        except queue.Empty:
            pass
        root.after(100, lire_events)

    bouton.configure(command=demarrer)
    root.after(100, lire_events)

    maj_categorie()
    maj_format()
    maj_vide()
    if not ffmpeg:
        afficher("FFmpeg est introuvable : la conversion est indisponible.",
                 ERREUR)
        bouton.configure(state="disabled")
    cadre.focus_initial = lambda: None
    return cadre


if __name__ == "__main__":
    lancer_interface()
