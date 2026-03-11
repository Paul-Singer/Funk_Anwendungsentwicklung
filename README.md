Hinweise für den Test der Anwendung

Bitte die Ordnerstruktur so lassen, wie sie im Repository vorliegt. 



Das Container-Image liegt in der GitHub Container Registry und kann direkt von dort geladen und gestartet werden. Voraussetzung ist eine funktionierende Docker-Installation.

Image laden
Zuerst das Image aus der Registry herunterladen:

docker pull ghcr.io/<owner>/anwendungsentwicklung-ghcn:latest

Container starten
Anschließend den Container starten und den Port 8080 nach außen weiterleiten:

docker run --rm -p 8080:8080 ghcr.io/<owner>/anwendungsentwicklung-ghcn:latest

Anwendung öffnen
Im Browser aufrufen:

http://localhost:8080

Hinweise

Falls Port 8080 bereits belegt ist, kann alternativ z. B. 8081 verwendet werden: docker run --rm -p 8081:8080 … und dann http://localhost:8081
 öffnen.

 PowerShell Startbefehl:
docker compose up --build -d; Start-Process http://localhost:8080/

PowerShell Stopbefehl:
docker compose down
