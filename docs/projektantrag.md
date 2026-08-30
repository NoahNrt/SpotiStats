# Antrag für die betriebliche Projektarbeit

## 1. Projektbezeichnung

**Entwicklung einer webbasierten Software zur statistischen Analyse und Visualisierung persönlicher Spotify-Hördaten**

### 1.1 Kurzform der Aufgabenstellung

Für NoahNrt e.V. soll eine Software entwickelt werden, die persönliche Spotify-Hördaten erfasst und auswertet, um das eigene Hörverhalten, bevorzugte Musikrichtungen sowie interessante Zusammenhänge zwischen gehörten Songs und Künstlern besser zu verstehen. Die gewonnenen Daten sollen statistisch analysiert und übersichtlich in Diagrammen und Statistiken dargestellt werden.

### 1.2 Ist-Analyse

Für NoahNrt e.V. stehen derzeit persönliche Spotify-Hördaten zur Verfügung, die über Spotify abgerufen bzw. aus den von Spotify bereitgestellten Daten exportiert werden können. Eine eigene Anwendung zur zentralen Speicherung, Aufbereitung und Analyse dieser Daten existiert bisher nicht.

Spotify bietet zwar bereits einige grundlegende Statistiken zum eigenen Hörverhalten an, diese sind jedoch nur eingeschränkt anpassbar und bieten keine detaillierte Auswertung über längere Zeiträume. Insbesondere eine individuelle Analyse der bevorzugten Musikrichtungen, der meistgehörten Songs und Künstler sowie des eigenen Hörverhaltens ist nur begrenzt möglich.

Daher besteht der aktuelle Zustand darin, dass die vorhandenen Daten zwar verfügbar sind, jedoch keine zentrale Möglichkeit besteht, diese nach eigenen Kriterien auszuwerten und übersichtlich miteinander zu vergleichen. Die geplante Software soll diese Lücke schließen und eine individuelle statistische Auswertung der persönlichen Hördaten ermöglichen.

## 2. Zielsetzung entwickeln / Soll-Konzept

### 2.1 Was soll am Ende des Projektes erreicht sein?

Am Ende des Projektes soll eine funktionsfähige Anwendung zur Verfügung stehen, die Spotify-Hördaten einlesen und dauerhaft speichern kann. Die gespeicherten Daten sollen automatisch ausgewertet und dem Nutzer übersichtlich präsentiert werden.

Der Nutzer soll dadurch beispielsweise erkennen können, welche Musikrichtungen er bevorzugt, welche Künstler und Songs er am häufigsten hört und wie sich sein Musikgeschmack über die Zeit verändert. Die wichtigsten Ergebnisse sollen durch geeignete Diagramme und Statistiken verständlich visualisiert werden.

### 2.2 Welche Anforderungen müssen erfüllt sein?

- Import von Spotify-Hördaten über die Spotify-API bzw. bereitgestellte Spotify-Daten
- Speicherung der Hördaten in einer geeigneten Datenbank
- Analyse des persönlichen Hörverhaltens anhand verschiedener statistischer Kennzahlen
- Auswertung von Songs und Künstlern, beispielsweise meistgehörte Songs und Künstler
- Analyse der bevorzugten Musikrichtungen und Genres
- Zeitliche Auswertungen, um Veränderungen des Hörverhaltens über verschiedene Zeiträume erkennen zu können
- Visualisierung der Ergebnisse durch übersichtliche Diagramme und Statistiken
- Übersichtliche Benutzeroberfläche zur Darstellung und Auswahl der verschiedenen Auswertungen
- Nachvollziehbare und korrekte Berechnung der dargestellten Statistiken
- Erweiterbarkeit, sodass zukünftig weitere Statistiken und Analysefunktionen hinzugefügt werden können

### 2.3 Welche Einschränkungen müssen berücksichtigt werden?

Die Anwendung ist auf die von Spotify bereitgestellten Daten und die verfügbaren Funktionen der Spotify-API beschränkt. Zudem müssen die Datenschutzbestimmungen sowie die Authentifizierung und die Begrenzung der API-Anfragen berücksichtigt werden.

## 3. Projektstrukturplan entwickeln

### 3.1 Was ist zur Erfüllung der Zielsetzung erforderlich?

Zur Erfüllung der Zielsetzung ist eine schrittweise Entwicklung der Anwendung mit anschließender Prüfung der einzelnen Funktionen erforderlich. Das Projekt wird dabei iterativ umgesetzt und durch regelmäßige Rücksprachen mit dem Fachbereich begleitet, um Feedback zur Funktionalität, Benutzerfreundlichkeit und Darstellung der Statistiken einzuholen. Zusätzlich sind geeignete Entwicklungswerkzeuge, die Spotify-API, eine Datenbank sowie eine Testumgebung erforderlich.

### 3.2 Aufgaben auflisten

- **Analyse**
  - Durchführung einer Ist-Analyse
  - Durchführung einer Wirtschaftlichkeitsanalyse
  - Ermittlung der Anforderungen und Use-Cases
  - Analyse der verfügbaren Spotify-Daten und API-Schnittstellen
  - Erstellung eines Lastenheftes
- **Entwurf**
  - Entwurf der Datenbankstruktur
  - Erstellung eines System- bzw. Komponentendiagramms
  - Planung der Schnittstelle zur Spotify-API
  - Entwurf der Benutzeroberfläche
  - Planung der verschiedenen Statistik- und Analysefunktionen
  - Erstellung eines Pflichtenheftes
- **Implementierung**
  - Implementierung der Spotify-API-Anbindung mit Tests
  - Implementierung der Datenbank und Speicherung der Hördaten
  - Implementierung der statistischen Auswertungen mit Tests
  - Implementierung der Diagramme und Visualisierungen
  - Implementierung der Benutzeroberfläche
  - Integration und Zusammenspiel der einzelnen Komponenten
- **Abnahme und Einführung**
  - Durchführung von Funktionstests
  - Überprüfung der berechneten Statistiken auf korrekte Ergebnisse
  - Durchführung von Tests mit realen Spotify-Hördaten
  - Vorstellung und Abnahme der Anwendung durch den Fachbereich
  - Einarbeitung des erhaltenen Feedbacks
- **Dokumentation**
  - Erstellung der Projektdokumentation
  - Erstellung einer technischen Dokumentation
  - Dokumentation der Datenbank und Schnittstellen
  - Erstellung eines Benutzerhandbuches

### 3.3 Grafische und tabellarische Darstellung

| Phase | Dauer in Stunden |
| --- | --- |
| Analyse | 9 |
| Entwurf | 12 |
| Implementierung | 43 |
| Abnahme und Deployment | 6 |
| Dokumentation | 10 |
| **Summe** | **80** |

## 4. Projektphasen mit Zeitplanung in Stunden

| Aufgabe | Dauer |
| --- | --- |
| **Analyse** | **9 h** |
| Ist-Analyse der vorhandenen Spotify-Daten und Funktionen durchführen | 2 h |
| Anforderungen und Zielsetzung des Projektes analysieren | 2 h |
| Wirtschaftlichkeitsprüfung des Projektes durchführen | 1 h |
| Use-Cases und Anforderungen ermitteln | 2 h |
| Lastenheft erstellen | 2 h |
| **Entwurf** | **12 h** |
| Datenbankstruktur entwerfen | 3 h |
| Komponentendiagramm erstellen | 2 h |
| Schnittstelle zur Spotify-API entwerfen | 2 h |
| Konzept für die statistischen Auswertungen erstellen | 2 h |
| Entwurf der Benutzeroberfläche erstellen | 2 h |
| Pflichtenheft erstellen | 1 h |
| **Implementierung** | **43 h** |
| Implementierung der Spotify-API-Anbindung mit Tests | 10 h |
| &nbsp;&nbsp;– Authentifizierung und Verbindung zur Spotify-API | 3 h |
| &nbsp;&nbsp;– Abrufen und Aufbereiten der Spotify-Daten | 5 h |
| &nbsp;&nbsp;– Fehlerbehandlung und Tests | 2 h |
| Implementierung der Datenbank | 8 h |
| &nbsp;&nbsp;– Erstellung der Datenbankstruktur | 3 h |
| &nbsp;&nbsp;– Implementierung der Speicherung und Abfrage der Hördaten | 3 h |
| &nbsp;&nbsp;– Tests der Datenbankfunktionen | 2 h |
| Implementierung der statistischen Auswertungen mit Tests | 15 h |
| &nbsp;&nbsp;– Auswertung von Songs und Künstlern | 4 h |
| &nbsp;&nbsp;– Analyse der Musikrichtungen und Genres | 3 h |
| &nbsp;&nbsp;– Zeitliche Auswertung des Hörverhaltens | 4 h |
| &nbsp;&nbsp;– Weitere Kennzahlen und Statistiken | 2 h |
| &nbsp;&nbsp;– Tests der Analysefunktionen | 2 h |
| Implementierung der Benutzeroberfläche und Diagramme | 10 h |
| &nbsp;&nbsp;– Aufbau der Benutzeroberfläche | 3 h |
| &nbsp;&nbsp;– Implementierung der Diagramme | 5 h |
| &nbsp;&nbsp;– Integration und Tests der Darstellung | 2 h |
| **Abnahme und Deployment** | **6 h** |
| Durchführung von Funktionstests | 2 h |
| Test mit realen Spotify-Hördaten | 1 h |
| Fehlerbehebung und Optimierung | 1 h |
| Deployment der Anwendung | 1 h |
| Abnahme und abschließende Überprüfung | 1 h |
| **Erstellen der Dokumentationen** | **10 h** |
| Erstellen der Projektdokumentation | 7 h |
| Erstellen der technischen Dokumentation | 2 h |
| Erstellen der Benutzerdokumentation | 1 h |
| **Gesamtdauer** | **80 h** |

## 5. Name der Ausbildungsstätte, in dem das Projekt durchgeführt wird

NoahNrt e.V.
GummiEntenAbteilung – GEA

### 5.1 Name des Ausbilders, bzw. Projektverantwortlichen mit Angabe der Tel. Nr.

NoahNrt
*(Hier Telefonnummer einfügen)*
