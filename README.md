Hinweise für den Test der Anwendung

Bitte die Ordnerstruktur so lassen, wie sie im Repository vorliegt. Wichtig ist vor allem, dass Dockerfile und docker-compose.yml im Hauptverzeichnis (Root) bleiben und nicht in einen Unterordner verschoben werden.

In dem Ordner date gibt es einen weiteren Unterordner dly, welcher eigentlich leer sein sollte. Da ein leerer Ordner in GitHub nicht angezeigt werden kann liegt dort eine dummy Datei die entfernt werden muss

Zum Testen die Anwendung ganz normal über Docker Compose starten und anschließend im Browser unter localhost:8080 öffnen.
