#!/usr/bin/env bash
# Installe Convertisseur pour l'utilisateur courant (Linux Mint / Ubuntu / Debian).
set -e
cd "$(dirname "$0")"
DEST="$HOME/.local/share/convertisseur"

manque=()
python3 -c "import tkinter" 2>/dev/null || manque+=(python3-tk)
python3 -c "import ensurepip" 2>/dev/null || manque+=(python3-venv)
if [ ${#manque[@]} -gt 0 ]; then
    echo "Installation des paquets système : ${manque[*]}"
    sudo apt-get install -y "${manque[@]}"
fi

echo "Préparation de l'environnement…"
mkdir -p "$DEST"
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install -q --upgrade pip
"$DEST/venv/bin/pip" install -q --upgrade -r requirements.txt
cp convertisseur.py conversion.py icone.svg "$DEST/"

mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/convertisseur.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Convertisseur
Comment=Télécharger YouTube/TikTok et convertir vidéos, musiques, images
Exec=$DEST/venv/bin/python $DEST/convertisseur.py
Icon=$DEST/icone.svg
Terminal=false
Categories=AudioVideo;Graphics;Network;
DESK

echo "Terminé. Lancez « Convertisseur » depuis le menu des applications."
echo "Pour mettre à jour plus tard (si YouTube change), relancez ce script."
