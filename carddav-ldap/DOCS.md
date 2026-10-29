# Home Assistant Add-on: CardDAV to OpenLDAP Bridge

## Einrichtung

### 1. Apple App-spezifisches Passwort
Jedes Familienmitglied benötigt ein eigenes app-spezifisches Passwort:
1. Öffne [appleid.apple.com](https://appleid.apple.com/).
2. Navigiere zu **Anmelden und Sicherheit** -> **App-spezifische Passwörter**.
3. Erstelle ein Passwort (z. B. "Festnetz-Telefonbuch").

### 2. Add-on konfigurieren
Trage in der Add-on-Konfiguration die Apple-IDs der Familienmitglieder ein:

```yaml
accounts:
  - user: "person1@icloud.com"
    pass: "xxxx-xxxx-xxxx-xxxx"
  - user: "person2@icloud.com"
    pass: "yyyy-yyyy-yyyy-yyyy"
default_country: "DE"
sync_interval_cron: "0 * * * *"
ldap_user: ""
ldap_pass: ""
```

* **Deduplizierung:** Kontakte mit denselben Nummern (egal ob als `+49 89...`, `089...` oder `0049 89...` gespeichert) werden automatisch zusammengeführt.
* **Passwortschutz:** Wenn `ldap_user` und `ldap_pass` leer bleiben, ist der LDAP-Server anonym (ohne Passwort) erreichbar. Wenn du dort Werte hinterlegst, muss sich das Telefon mit diesen Zugangsdaten authentifizieren.

### 3. Add-on starten
Starte das Add-on. Im Protokoll (Logs) siehst du:
- Die Verbindung zu allen konfigurierten iCloud-Accounts
- Die Anzahl gefundener und deduplizierter Kontakte
- Den Start des LDAP-Servers

---

## VoIP-Telefon Anbindung (z. B. Gigaset N670 IP PRO)

- **LDAP-Server:** `<IP deiner Home Assistant Instanz>`
- **Port:** `389`
- **Basis-DN:** `ou=contacts,dc=home,dc=local`
- **Authentifizierung:**
  - Wenn in HA leer: Benutzername & Passwort leer lassen
  - Wenn konfiguriert: Bind-DN `cn=<ldap_user>,dc=home,dc=local` und dein Passwort

### Attribut-Mapping
- **Anzeigename:** `cn`
- **Nachname:** `sn`
- **Vorname:** `givenName`
- **Büro / Arbeit:** `telephoneNumber`
- **Mobil / iPhone:** `mobile`
- **Privat / Zu Hause:** `homePhone`
- **Fax:** `facsimileTelephoneNumber`
