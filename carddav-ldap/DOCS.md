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

---

## Optionale UniFi Talk Integration

Um Kontakte automatisch direkt in **UniFi Talk** zu synchronisieren:

1. **Lokalen Benutzer auf UniFi Console erstellen:**
   - Gehe auf deiner UniFi Console (UDM / Cloud Key) auf **Admins** und lege einen lokalen Administrator (z. B. `ha-talk`) mit Rechten für UniFi Talk an.
2. **Im Add-on konfigurieren:**
   - `unifi_talk_enabled`: `true`
   - `unifi_talk_host`: IP deiner UniFi Console (z. B. `192.168.1.1`)
   - `unifi_talk_user`: `ha-talk`
   - `unifi_talk_pass`: Dein vergebenes Passwort
   - `unifi_talk_contact_list`: Name der Liste (z. B. `iCloud`)
   - `unifi_talk_verify_ssl`: `false` (bei lokalem selbstsigniertem Zertifikat)
3. Beim nächsten Sync-Lauf erscheinen alle Kontakte in UniFi Talk unter **Contacts** und stehen allen UniFi Talk Telefonen zur Verfügung.
4. Im Home Assistant `/share`-Verzeichnis wird parallel eine `unifi_talk_contacts.csv` als Backup abgelegt.
