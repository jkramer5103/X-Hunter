# Schritt 1: Basis-Image auswählen
# Wähle eine passende Python-Version (z.B. 3.11 oder 3.12).
# Die 'slim'-Variante ist kleiner.
FROM python:3.11-slim

# Schritt 2: Arbeitsverzeichnis im Container festlegen
WORKDIR /app

# Schritt 3: Abhängigkeiten installieren
# Kopiere zuerst nur die requirements.txt, um Docker's Caching zu nutzen.
COPY requirements.txt .
# Installiere die Pakete. --no-cache-dir hält das Image kleiner.
RUN pip install --no-cache-dir -r requirements.txt

# Schritt 4: App-Code kopieren
# Kopiere den gesamten Inhalt des aktuellen Verzeichnisses (.) in das Arbeitsverzeichnis (/app) im Container.
COPY . .

# Schritt 5: Port freigeben (Dokumentation)
# Informiert Docker, dass der Container auf diesem Port lauscht.
# Deine App läuft auf Port 1432.
EXPOSE 1432

# Schritt 6: Startbefehl definieren
# Dieser Befehl wird ausgeführt, wenn der Container startet.
# Verwende eventlet zum Starten für SocketIO.
# Wichtig: host='0.0.0.0' ist entscheidend, damit die App von außerhalb des Containers erreichbar ist.
# Der Port wird hier *nicht* explizit angegeben, da app.py ihn definiert.
# Wenn dein app.py eventlet nicht direkt verwendet, sondern nur socketio.run,
# reicht oft auch ["python", "app.py"]. Aber da wir eventlet für SocketIO
# installiert haben, ist es besser, es explizit zu nutzen, falls app.py
# es nicht schon tut. Da dein app.py socketio.run verwendet, ist
# ["python", "app.py"] der richtige Befehl.
CMD ["python", "app.py"]
