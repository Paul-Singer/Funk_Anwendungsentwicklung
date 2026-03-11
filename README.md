Voraussetzungen:

Docker ist installiert und läuft.

Internetverbindung ist vorhanden.




Projektordnerstruktur:

Dockerfile und docker-compose.yml liegen im Root-Verzeichnis des Repositories.

Die Ordnerstruktur bitte genauso beibehalten, wie sie in GitHub vorgegeben ist.




Starten:

Docker-Image aus GitHub Packages laden:
docker pull ghcr.io/paul-singer/funk_anwendungsentwicklung:latest

Container starten (Port 8080):
docker run --rm -p 8080:8080 ghcr.io/paul-singer/funk_anwendungsentwicklung:latest

Anwendung im Browser öffnen:
http://localhost:8080
