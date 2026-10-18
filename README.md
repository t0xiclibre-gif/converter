# Convertisseur

Petite application sobre, sans pub, qui travaille entièrement sur votre
ordinateur (rien n'est envoyé ailleurs). Deux onglets :

- **Télécharger** : une vidéo **YouTube** ou **TikTok** en **MP3**
  (320 kbit/s) ou **MP4** (jusqu'à la 4K). Coller le lien → choisir MP3 ou
  MP4 → **Télécharger**.
- **Convertir des fichiers** : vos vidéos, musiques et images d'un format à
  l'autre, un fichier ou des centaines d'un coup.

## Onglet « Convertir des fichiers »

1. Ajoutez des fichiers (bouton, dossier entier avec ses sous-dossiers, ou
   glisser-déposer dans la liste).
2. Choisissez **Vers vidéo**, **Vers audio** ou **Vers image**, puis le format.
3. Réglez les options si besoin, puis **Convertir**.

Les fichiers incompatibles avec le format choisi (une musique vers une image,
par exemple) sont simplement ignorés ; cliquez sur une ligne pour voir le
détail d'une erreur, double-cliquez pour ouvrir son dossier. Un fichier
existant n'est jamais écrasé : « nom (2).mp4 » est créé à la place.

| Vers | Formats |
|------|---------|
| Vidéo | MP4, MKV, WebM, MOV, AVI, M4V, WMV, FLV, TS, MPEG, 3GP, OGV, GIF animé, WebP animé |
| Audio | MP3, M4A (AAC), Opus, OGG Vorbis, WMA, AC3, FLAC, M4A (ALAC), WAV, AIFF, WavPack |
| Image | PNG, JPEG, WebP, AVIF, JPEG XL\*, BMP, TIFF, GIF, ICO, TGA, JPEG 2000, QOI, PPM |

\* Seuls les formats que votre FFmpeg sait écrire sont proposés.

En entrée, tout ce que FFmpeg sait lire : MP4, MKV, MOV, AVI, WebM, MTS,
VOB, FLV, WMV, MP3, FLAC, WAV, M4A, OGG, Opus, WMA, AIFF, APE, PNG, JPEG,
WebP, AVIF, TIFF, BMP, GIF, TGA, PSD…

Options disponibles selon le format :

- **Vidéo** : codec (H.264, H.265, VP9, AV1, MPEG-4, ProRes…, ou copie
  sans réencodage, quasi instantanée), qualité, résolution (4K à 240p, jamais
  agrandie), images/s, vitesse d'encodage, son (débit, copie ou sans son),
  rotation / miroir.
- **GIF / WebP animé** : largeur, images/s, qualité.
- **Audio** : débit, fréquence, stéréo / mono (extrait aussi le son d'une
  vidéo).
- **Image** : qualité, taille maximale ou pourcentage, rotation / miroir.
  Depuis une vidéo, une image est capturée au moment indiqué.
- **Commun** : découpe (début / fin, ex. `1:30`), normalisation du volume,
  dossier de destination ou à côté des originaux.

## Linux Mint

```bash
./install_linux.sh
```

L'appli apparaît ensuite dans le menu sous « Convertisseur ».
Relancer le script de temps en temps met à jour le moteur (utile si YouTube change).

## Windows

1. Installer Python depuis https://www.python.org (cocher « Add python.exe to PATH »).
2. Double-cliquer sur `build_windows.bat`.
3. Le programme autonome est créé dans `dist\Convertisseur.exe` (FFmpeg inclus,
   rien d'autre à installer). Vous pouvez le copier où vous voulez.

## Notes

- Les fichiers vont par défaut dans le dossier Téléchargements (modifiable).
- Les MP4 privilégient le H.264 ; au-delà de 1080p, YouTube ne fournit que du
  VP9/AV1 (lisible avec VLC ou les lecteurs récents). Choisir « 1080p » pour une
  compatibilité maximale.
- AV1 et VP9 compressent mieux mais sont nettement plus lents à encoder que
  H.264.
- Le glisser-déposer nécessite le paquet `tkinterdnd2` (installé
  automatiquement) ; sans lui, les boutons d'ajout fonctionnent toujours.
- Téléchargez uniquement des contenus que vous avez le droit de copier.
