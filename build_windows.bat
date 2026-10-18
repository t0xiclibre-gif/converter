@echo off
REM Construit dist\Convertisseur.exe (nécessite Python 3.10+ installé depuis python.org)
cd /d "%~dp0"
python -m venv .venv || goto :erreur
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller pillow || goto :erreur
python -c "from PIL import Image, ImageDraw; s=256; im=Image.new('RGBA',(s,s)); d=ImageDraw.Draw(im); d.rounded_rectangle((0,0,s-1,s-1),56,fill='#1d1d1f'); c='#f6f6f4'; d.line((128,64,128,164),fill=c,width=20); d.line((84,124,128,168,172,124),fill=c,width=20,joint='curve'); d.line((76,196,180,196),fill=c,width=20); im.save('icone.ico',sizes=[(256,256),(64,64),(32,32),(16,16)])"
python build.py || goto :erreur
echo.
echo Termine : dist\Convertisseur.exe
pause
exit /b 0
:erreur
echo La construction a echoue.
pause
exit /b 1
