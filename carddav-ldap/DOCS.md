# Home Assistant Add-on: CardDAV to OpenLDAP Bridge

## Einrichtung

### 1. Apple App-spezifisches Passwort
Apple erlaubt CardDAV-Zugriffe von Drittanwendungen nur über anwendungsspezifische Passwörter:
1. Öffne [appleid.apple.com](https://appleid.apple.com/).
2. Navigiere zu **Anmelden und Sicherheit** -> **App-spezifische Passwörter**.
3. Erstelle ein Passwort (z. B. "HA-LDAP").

### 2. Add-on konfigurieren
Trage in der Add-on-Konfiguration deine Apple-ID und das generierte App-Passwort ein:

```yaml
icloud_user: "deine.apple.id@icloud.com"
icloud_pass: "xxxx-xxxx-xxxx-xxxx"
sync_interval_cron: "0 * * * *"
```

### 3. Add-on starten
Starte das Add-on. Im Protokoll (Logs) siehst du:
- Den Start des LDAP-Servers
- Den initialen Sync mit deinen iCloud-Kontakten

---

## VoIP-Telefon Anbindung (z. B. Gigaset N670 IP PRO)

- **LDAP-Server:** `<IP deiner Home Assistant Instanz>`
- **Port:** `389`
- **Basis-DN:** `ou=contacts,dc=home,dc=local`
- **Bind-DN:** `cn=admin,dc=home,dc=local`
- **Passwort:** `admin`

### Attribut-Mapping
- **Vorname:** `givenName`
- **Nachname:** `sn`
- **Anzeigename:** `cn`
- **Telefonnummer:** `telephoneNumber`
