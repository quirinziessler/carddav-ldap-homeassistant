# Home Assistant Add-on: CardDAV to OpenLDAP Bridge

[![Build and Publish HA Add-on](https://github.com/quirinziessler/carddav-ldap-homeassistant/actions/workflows/publish.yaml/badge.svg)](https://github.com/quirinziessler/carddav-ldap-homeassistant/actions/workflows/publish.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-blue)

Ein Home Assistant Add-on, das Kontakte aus einem **Apple iCloud CardDAV-Adressbuch** automatisch in einen lokalen **OpenLDAP-Server (`slapd`)** synchronisiert.

Ideal geeignet als **zentrales Telefonbuch** für VoIP-Telefonsysteme wie die **Gigaset N670 / N870 IP PRO** DECT-Basis, Gigaset Maxwell, Yealink, Snom oder andere LDAP-fähige IP-Telefone.

---

## 🚀 Features

- 🍏 **iCloud CardDAV Sync:** Synchronisiert automatisch Kontakte aus Apple iCloud.
- 📇 **Integrierter OpenLDAP-Server:** Eigener vollwertiger `slapd`-Dienst auf Standardport `389` (MDB-Backend).
- ⏱ **Automatischer Cronjob:** Konfigurierbares Synchronisationsintervall (standardmäßig stündlich).
- ☎️ **Gigaset IP PRO Optimiert:** Mappt Adressbuchdaten sauber in das Standard-`inetOrgPerson`-LDAP-Schema (`cn`, `givenName`, `sn`, `telephoneNumber`).
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

Vor dem Start muss das Add-on unter dem Reiter **Konfiguration** eingerichtet werden:

```yaml
icloud_user: "deine.apple.id@icloud.com"
icloud_pass: "xxxx-xxxx-xxxx-xxxx"
sync_interval_cron: "0 * * * *"
```

### Konfigurations-Optionen

| Option | Typ | Beschreibung |
| :--- | :--- | :--- |
| `icloud_user` | String | Deine Apple-ID E-Mail-Adresse. |
| `icloud_pass` | Password | Ein **anwendungsspezifisches Passwort** aus deinem Apple-Account (*nicht* dein normales Passwort!). |
| `sync_interval_cron` | String | Cron-Ausdruck für das Synchronisationsintervall (z. B. `0 * * * *` für stündlich oder `*/15 * * * *` für alle 15 Min). |

> [!TIP]
> **App-spezifisches Passwort erstellen:**
> 1. Melde dich auf [appleid.apple.com](https://appleid.apple.com/) an.
> 2. Gehe zu **Anmelden und Sicherheit** → **App-spezifische Passwörter**.
> 3. Erstelle ein neues Passwort (z. B. mit dem Namen "Home Assistant LDAP").

---

## 📞 Einrichtung im Gigaset N670 IP PRO

Um das Telefonbuch in der Gigaset N670 / N870 IP PRO Web-Oberfläche einzubinden:

1. Gehe im Webinterface der Gigaset-Basis zu **Einstellungen** → **Telefonie** → **LDAP** (bzw. **Online-Telefonbücher**).
2. Trage folgende Werte ein:

| Feld | Wert |
| :--- | :--- |
| **Serveradresse** | IP-Adresse deines Home Assistant Hosts |
| **Serverport** | `389` |
| **Basis-DN** | `ou=contacts,dc=home,dc=local` |
| **Benutzername (Bind DN)** | `cn=admin,dc=home,dc=local` |
| **Passwort** | `admin` |
| **Suchfilter** | `(&(objectClass=inetOrgPerson)(|(cn=*%*)(sn=*%*)(telephoneNumber=*%*)))` |

### Namens- und Nummern-Attribute (Mapping):
- **Name / Nachname (sn):** `sn`
- **Vorname (givenName):** `givenName`
- **Anzeigename (cn):** `cn`
- **Telefonnummer:** `telephoneNumber`

---

## 🛠 Architektur & Technik

Im Add-on Container laufen dank des Home Assistant `s6-overlay` zwei parallele Dienste:
1. **`slapd`**: Der OpenLDAP-Dienst, gebunden an Port `389` mit `mdb`-Backend.
2. **`crond` + `sync.py`**: Führt beim Containerstart einen initialen Abgleich durch und aktualisiert das Telefonbuch fortlaufend im definierten Intervall.

---

## 📄 Lizenz

Dieses Projekt ist lizenziert unter der [MIT Lizenz](LICENSE).
