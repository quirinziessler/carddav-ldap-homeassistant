# Home Assistant Add-on: CardDAV to OpenLDAP Bridge

[![Build and Publish HA Add-on](https://github.com/quirinziessler/carddav-ldap-homeassistant/actions/workflows/publish.yaml/badge.svg)](https://github.com/quirinziessler/carddav-ldap-homeassistant/actions/workflows/publish.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-blue)

Ein Home Assistant Add-on, das Kontakte aus einem oder **mehreren Apple iCloud CardDAV-Adressbüchern** automatisch in einen lokalen **OpenLDAP-Server (`slapd`)** synchronisiert.

Ideal geeignet als **zentrales Familien- und Firmen-Telefonbuch** für VoIP-Telefonsysteme wie die **Gigaset N670 / N870 IP PRO** DECT-Basis, Gigaset Maxwell, Yealink, Snom oder andere LDAP-fähige IP-Telefone.

---

## 🚀 Features

- 👨‍👩‍👧‍👦 **Multi-Apple-ID Support:** Synchronisiert Kontakte von mehreren Familienmitgliedern aus verschiedenen iCloud-Accounts zusammen.
- 🧠 **Smarte Deduplizierung & Normalisierung:**
  - Nutzt Google's `libphonenumber`-Standard zur Erkennung und Formatierung von Nummern.
  - Erkennt Dubletten über unterschiedliche Schreibweisen hinweg (z. B. `089 123456`, `+49 89 123456`, `0049 89 123456`, `+49 (0) 89 123456`).
  - **Intelligente Namenswahl:** Wenn Person A "Erna Müller" und Person B "Oma Erna" gespeichert hat, wird automatisch der vollständige Name gewählt und alle Nummern zusammengeführt!
- 📇 **Integrierter OpenLDAP-Server:** Eigener vollwertiger `slapd`-Dienst auf Standardport `389` (MDB-Backend).
- 📱 **Smarte Nummern-Zuordnung:** Erkennt und trennt:
  - 🏠 **Privatnummer** (`homePhone`)
  - 📱 **Mobil / iPhone** (`mobile`)
  - 🏢 **Arbeitsnummer / Büro** (`telephoneNumber`)
  - 📠 **Fax** (`facsimileTelephoneNumber`)
- 🔒 **Flexible Authentifizierung:**
  - **Ohne Passwort (Anonymous Bind):** Ideal für ein geschütztes Heim-/Büronetzwerk. Keine Zugangsdaten am Telefon nötig.
  - **Mit Benutzername & Passwort:** Voller Schutz gegen unbefugte Abfragen.
- 🧹 **Automatische Bereinigung:** Kontakte, die in iCloud gelöscht werden, verschwinden automatisch auch aus dem LDAP-Telefonbuch.
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

Unter dem Reiter **Konfiguration** kannst du beliebig viele Apple-IDs hinterlegen:

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
```

### Konfigurations-Optionen

| Option | Typ | Standard | Beschreibung |
| :--- | :--- | :--- | :--- |
| `accounts` | Liste | *(mind. 1)* | Liste aller Apple-IDs mit jeweils einem **app-spezifischen Passwort**. |
| `default_country` | String | `"DE"` | Zweibuchstabiger Ländercode (z. B. `DE`, `AT`, `CH`) zur korrekten Erkennung lokaler Nummern ohne Ländervorwahl. |
| `sync_interval_cron` | String | `0 * * * *` | Cron-Ausdruck für das Sync-Intervall (z. B. `0 * * * *` für stündlich oder `*/15 * * * *` für alle 15 Min). |
| `ldap_user` | String | `""` *(leer)* | Optionaler LDAP-Benutzername. Wenn leer, ist kein Passwort am Telefon erforderlich (Anonymous Bind). |
| `ldap_pass` | Password | `""` *(leer)* | Optionales LDAP-Passwort. Nur aktiv, wenn auch `ldap_user` befüllt ist. |

> [!TIP]
> **App-spezifisches Passwort erstellen:**
> Jedes Familienmitglied meldet sich kurz auf [appleid.apple.com](https://appleid.apple.com/) an, geht auf **Anmelden und Sicherheit** → **App-spezifische Passwörter** und erstellt ein Passwort (z. B. "Festnetz-Telefonbuch").

---

## 📞 Einrichtung im Gigaset N670 IP PRO

Um das Telefonbuch in der Gigaset N670 / N870 IP PRO Web-Oberfläche einzubinden:

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

## 📄 Lizenz

Dieses Projekt ist lizenziert unter der [MIT Lizenz](LICENSE).
