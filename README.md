# Home Assistant Add-on: CardDAV to OpenLDAP Bridge

[![Build and Publish HA Add-on](https://github.com/quirinziessler/carddav-ldap-homeassistant/actions/workflows/publish.yaml/badge.svg)](https://github.com/quirinziessler/carddav-ldap-homeassistant/actions/workflows/publish.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-blue)

Ein Home Assistant Add-on, das Kontakte aus einem oder **mehreren Apple iCloud CardDAV-Adressbüchern** automatisch in einen lokalen **OpenLDAP-Server (`slapd`)** und optional direkt in **UniFi Talk** synchronisiert.

Ideal geeignet als **zentrales Familien- und Firmen-Telefonbuch** für VoIP-Telefonsysteme wie die **Gigaset N670 / N870 IP PRO** DECT-Basis, Gigaset Maxwell, Yealink, Snom sowie **UniFi Talk** Telefone (Touch, Touch Max, Flex).

---

## 🚀 Features

- 👨‍👩‍👧‍👦 **Multi-Apple-ID Support:** Synchronisiert Kontakte von mehreren Familienmitgliedern aus verschiedenen iCloud-Accounts zusammen.
- 🧠 **Smarte Deduplizierung & Normalisierung:**
  - Nutzt Google's `libphonenumber`-Standard zur Erkennung und Formatierung von Nummern.
  - Erkennt Dubletten über unterschiedliche Schreibweisen hinweg (z. B. `089 123456`, `+49 89 123456`, `0049 89 123456`).
  - **Intelligente Namenswahl:** Wenn Person A "Erna Müller" und Person B "Oma Erna" gespeichert hat, wird automatisch der vollständige Name gewählt und alle Nummern zusammengeführt!
- 📇 **Integrierter OpenLDAP-Server:** Eigener vollwertiger `slapd`-Dienst auf Standardport `389` (MDB-Backend).
- ☎️ **UniFi Talk Integration (Optional):**
  - Synchronisiert alle Kontakte per lokaler REST-API direkt in deine UniFi Console (UDM / Cloud Key).
  - Erstellt automatisch eine strukturierte Kontaktliste (z. B. `iCloud`) in UniFi Talk.
  - Schreibt parallel eine stets aktuelle CSV-Datei (`unifi_talk_contacts.csv`) in das `/share`-Verzeichnis von Home Assistant.
- 📱 **Smarte Nummern-Zuordnung:** Erkennt und trennt:
  - 🏠 **Privatnummer** (`homePhone` / Home)
  - 📱 **Mobil / iPhone** (`mobile` / Mobile)
  - 🏢 **Arbeitsnummer / Büro** (`telephoneNumber` / Work)
  - 📠 **Fax** (`facsimileTelephoneNumber`)
- 📞 **CLIP / Anrufernamens-Erkennung:**
  - Speichert Telefonnummern sowohl im internationalen Format (`+49 162...`) als auch im nationalen Format (`0162...`).
  - Eingehende Anrufe von Providern wie Telekom, Vodafone oder FRITZ!Box werden sofort mit dem Kontaktnamen im Telefondisplay gematcht.
- 🔒 **Flexible Authentifizierung:**
  - **Ohne Passwort (Anonymous Bind):** Ideal für ein geschütztes Heimnetzwerk. Keine Zugangsdaten am Telefon nötig.
  - **Mit Benutzername & Passwort:** Voller Schutz gegen unbefugte Abfragen.
- 🧹 **Automatische Bereinigung:** In iCloud gelöschte Kontakte verschwinden automatisch auch aus OpenLDAP und UniFi Talk.
- ⏱ **Automatischer Cronjob:** Konfigurierbares Synchronisationsintervall (standardmäßig stündlich).
- 🏗 **Multi-Architektur:** Unterstützt `aarch64` (z. B. Raspberry Pi 4/5, Home Assistant Green/Yellow) und `amd64` (Intel/AMD x86_64 VMs, NUC, etc.).

---

## 📦 Installation in Home Assistant

1. Öffne deine Home Assistant Oberfläche.
2. Navigiere zu **Einstellungen** → **Add-ons** → **Add-on Store** (unten rechts).
3. Klicke oben rechts auf das Drei-Punkte-Menü (`⋮`) → **Repositories**.
4. Füge folgendes Repository hinzu:
   ```text
   https://github.com/quirinziessler/carddav-ldap-homeassistant
   ```
5. Suche im Store nach **"CardDAV to OpenLDAP Bridge"** und klicke auf **Installieren**.

---

## ⚙️ Konfiguration

Unter dem Reiter **Konfiguration** kannst du die Einstellungen hinterlegen:

```yaml
accounts:
  - user: "papa@icloud.com"
    pass: "xxxx-xxxx-xxxx-xxxx"
  - user: "mama@icloud.com"
    pass: "yyyy-yyyy-yyyy-yyyy"
default_country: "DE"
sync_interval_cron: "0 * * * *"
ldap_user: ""
ldap_pass: ""

# Optionale UniFi Talk Synchronisation:
unifi_talk_enabled: true
unifi_talk_host: "192.168.1.1"
unifi_talk_user: "dein_unifi_benutzer"
unifi_talk_pass: "dein_unifi_passwort"
unifi_talk_contact_list: "iCloud"
unifi_talk_verify_ssl: false
```

### Konfigurations-Optionen

| Option | Typ | Standard | Beschreibung |
| :--- | :--- | :--- | :--- |
| `accounts` | Liste | *(mind. 1)* | Liste aller Apple-IDs mit jeweils einem **app-spezifischen Passwort**. |
| `default_country` | String | `"DE"` | Zweibuchstabiger Ländercode (z. B. `DE`, `AT`, `CH`) zur korrekten Erkennung lokaler Nummern ohne Ländervorwahl. |
| `sync_interval_cron` | String | `0 * * * *` | Cron-Ausdruck für das Sync-Intervall (z. B. `0 * * * *` für stündlich oder `*/15 * * * *` für alle 15 Min). |
| `ldap_user` | String | `""` *(leer)* | Optionaler LDAP-Benutzername. Wenn leer, ist kein Passwort am Telefon erforderlich (Anonymous Bind). |
| `ldap_pass` | Password | `""` *(leer)* | Optionales LDAP-Passwort. Nur aktiv, wenn auch `ldap_user` befüllt ist. |
| `unifi_talk_enabled` | Boolean | `false` | Aktiviert die direkte Synchronisation in UniFi Talk. |
| `unifi_talk_host` | String | `""` *(leer)* | IP-Adresse oder Hostname deiner UniFi Console (z. B. `192.168.1.1`). |
| `unifi_talk_user` | String | `""` *(leer)* | Lokaler Administrator-Benutzername auf UniFi OS. |
| `unifi_talk_pass` | Password | `""` *(leer)* | Passwort für den UniFi OS Benutzer. |
| `unifi_talk_contact_list` | String | `"iCloud"` | Name der Kontaktliste in UniFi Talk. |
| `unifi_talk_verify_ssl` | Boolean | `false` | SSL-Zertifikat prüfen (bei selbstsignierten Zertifikaten im LAN auf `false` lassen). |

> [!TIP]
> **App-spezifisches Passwort erstellen:**
> Jedes Familienmitglied meldet sich kurz auf [appleid.apple.com](https://appleid.apple.com/) an, geht auf **Anmelden und Sicherheit** → **App-spezifische Passwörter** und erstellt ein Passwort (z. B. "Festnetz-Telefonbuch").

---

## 📞 Einrichtung im Gigaset N670 IP PRO

1. Gehe im Webinterface der Gigaset-Basis zu **Einstellungen** → **Telefonie** → **LDAP** (bzw. **Online-Telefonbücher**).
2. Trage folgende Werte ein:

### Grunddaten:
- **Serveradresse:** IP-Adresse deines Home Assistant Hosts
- **Serverport:** `389`
- **Basis-DN:** `ou=contacts,dc=home,dc=local`

### Authentifizierung:
- **Variante A: Ohne Passwort (wenn `ldap_user` & `ldap_pass` in HA leer sind):**
  - **Benutzername:** *(leer lassen / Anonymous Bind aktivieren)*
  - **Passwort:** *(leer lassen)*
- **Variante B: Mit Passwort (wenn z. B. `ldap_user: "telefon"` und `ldap_pass: "geheim"` konfiguriert sind):**
  - **Benutzername (Bind DN):** `cn=telefon,dc=home,dc=local`
  - **Passwort:** `geheim`

### Suchfilter:
```text
(&(objectClass=inetOrgPerson)(|(cn=*%*)(sn=*%*)(telephoneNumber=*%*)(homePhone=*%*)(mobile=*%*)))
```

### Namens- und Nummern-Attribute (Mapping):
| Gigaset Feld | LDAP Attribut | Herkunft aus iCloud |
| :--- | :--- | :--- |
| **Anzeigename** | `cn` | Vollständiger Name |
| **Nachname** | `sn` | Nachname |
| **Vorname** | `givenName` | Vorname |
| **Büro / Telefon (geschäftlich)** | `telephoneNumber` | Arbeitsnummer (`WORK`) / Hauptnummer |
| **Mobiltelefon** | `mobile` | Mobil / iPhone (`CELL`, `IPHONE`) |
| **Privattelefon** | `homePhone` | Privatnummer (`HOME`, `PRIVATE`) |
| **Fax** | `facsimileTelephoneNumber` | Faxnummer (`FAX`) |

---

## 🖲️ Einrichtung in UniFi Talk

Falls aktiviert, synchronisiert das Add-on alle Kontakte vollautomatisch in UniFi Talk.

1. **Lokalen UniFi Benutzer anlegen:**
   * Öffne deine UniFi Console (z. B. `https://192.168.1.1`).
   * Gehe zu **OS Settings** → **Admins & Users** → **Admins**.
   * Erstelle einen neuen lokalen Administrator (z. B. `ha-talk`) mit Zugriff auf **Talk** (Berechtigung: Full Management oder Administrator).
2. **In Home Assistant eintragen:**
   * Trage die IP-Adresse deiner UniFi Console, den Benutzernamen und das Passwort in den Add-on-Einstellungen ein.
   * Aktiviere `unifi_talk_enabled: true`.
3. **Fertig:**
   * Beim nächsten Sync findest du alle Kontakte unter **UniFi Talk** → **Contacts** in der Liste **iCloud**.
   * Alle UniFi Talk Telefone (Touch, Touch Max, Flex) zeigen diese Kontakte sofort auf ihren Displays an!

---

## 📄 Lizenz

Dieses Projekt ist lizenziert unter der [MIT Lizenz](LICENSE).
