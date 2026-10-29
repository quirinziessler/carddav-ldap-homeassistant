import os
import re
import json
import caldav
import phonenumbers
from ldap3 import Server, Connection, ALL, MODIFY_REPLACE
try:
    from ldap3.utils.dn import escape_rdn
except ImportError:
    def escape_rdn(s):
        for c in (',', '+', '=', '"', '\\', '<', '>', ';'):
            s = s.replace(c, f'\\{c}')
        return s

def get_ha_config():
    with open('/data/options.json') as f:
        return json.load(f)

def get_accounts(config):
    accounts = []
    # Liste von Accounts (neues Format)
    if 'accounts' in config and isinstance(config['accounts'], list):
        for acc in config['accounts']:
            user = (acc.get('user') or '').strip()
            password = (acc.get('pass') or '').strip()
            if user and password:
                accounts.append({'user': user, 'pass': password})

    # Fallback auf altes Einzel-Account-Format
    if not accounts:
        user = (config.get('icloud_user') or '').strip()
        password = (config.get('icloud_pass') or '').strip()
        if user and password:
            accounts.append({'user': user, 'pass': password})

    return accounts

def normalize_number(raw_num, default_country="DE"):
    """
    Normalisiert eine Telefonnummer:
    - Liefert (canonical, display)
    - canonical: E.164 (+49891234567) fuer den exakten Vergleich
    - display: Internationales Format (+49 89 1234567) fuers Telefonbuch
    """
    if not raw_num:
        return None, None
    clean = str(raw_num).strip()
    if not clean:
        return None, None

    try:
        parsed = phonenumbers.parse(clean, default_country)
        if phonenumbers.is_possible_number(parsed):
            canonical = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            display = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            return canonical, display
    except Exception:
        pass

    # Fallback bei Durchwahlen, Notruf- oder Sondernummern
    digits = re.sub(r'[^\d+]', '', clean)
    if digits.startswith('00'):
        digits = '+' + digits[2:]
    elif digits.startswith('+490'):
        digits = '+49' + digits[4:]
    return digits, clean

class MergedContact:
    def __init__(self, fn, family_name, given_name):
        self.fn = fn
        self.family_name = family_name
        self.given_name = given_name
        self.home_numbers = set()
        self.work_numbers = set()
        self.mobile_numbers = set()
        self.fax_numbers = set()
        self.other_numbers = set()
        self.canonical_numbers = set()

def name_quality(fn, family, given):
    score = 0
    fn_clean = (fn or '').strip()
    fam_clean = (family or '').strip()
    giv_clean = (given or '').strip()

    # Strukturierter Vor- und Nachname hat höchste Prioritaet
    if fam_clean and giv_clean and fam_clean != fn_clean and giv_clean != fn_clean:
        score += 100
    elif fam_clean and fam_clean != fn_clean:
        score += 40

    score += min(len(fn_clean), 30)

    # Informelle Rufnamen/Kosenamen abwerten, wenn ein voller Name zur Wahl steht
    if fn_clean.lower() in ('mama', 'papa', 'mami', 'papi', 'mum', 'dad', 'oma', 'opa'):
        score -= 60

    return score

def sync_contacts():
    config = get_ha_config()
    accounts = get_accounts(config)
    default_country = config.get('default_country', 'DE').upper().strip() or 'DE'

    if not accounts:
        print("Keine iCloud Accounts konfiguriert. Abbruch.")
        return

    print(f"Starte Sync für {len(accounts)} iCloud-Account(s) (Standardland: {default_country})...")

    # Liste aller zusammengefuehrten Kontakte
    merged_contacts = []

    for acc_idx, acc in enumerate(accounts, start=1):
        user = acc['user']
        print(f"[{acc_idx}/{len(accounts)}] Verbinde mit iCloud für {user}...")
        try:
            client = caldav.DAVClient(
                url="https://contacts.icloud.com",
                username=user,
                password=acc['pass']
            )
            principal = client.principal()
            addressbooks = principal.addressbooks()
        except Exception as e:
            print(f"Fehler bei Verbindung mit {user}: {e}")
            continue

        for book in addressbooks:
            try:
                contacts = book.contacts()
            except Exception as e:
                print(f"Fehler beim Laden des Adressbuchs von {user}: {e}")
                continue

            for contact in contacts:
                try:
                    vcard = contact.vobject_instance
                except Exception:
                    continue

                if not hasattr(vcard, 'fn') or not hasattr(vcard, 'tel'):
                    continue

                fn = str(vcard.fn.value).strip()
                if not fn:
                    continue

                family_name = getattr(vcard, 'n', fn).value.family if hasattr(vcard, 'n') else fn
                given_name = getattr(vcard, 'n', fn).value.given if hasattr(vcard, 'n') else ''
                if not family_name:
                    family_name = fn

                # Nummern dieses Kontakts extrahieren
                temp_home = set()
                temp_work = set()
                temp_mobile = set()
                temp_fax = set()
                temp_other = set()
                temp_canonical = set()

                tel_entries = getattr(vcard, 'contents', {}).get('tel', [])
                for tel in tel_entries:
                    raw_val = getattr(tel, 'value', '')
                    canonical, display = normalize_number(raw_val, default_country)
                    if not canonical:
                        continue

                    temp_canonical.add(canonical)

                    types = []
                    if hasattr(tel, 'params') and 'TYPE' in tel.params:
                        type_param = tel.params['TYPE']
                        if isinstance(type_param, list):
                            types = [t.upper() for t in type_param]
                        elif isinstance(type_param, str):
                            types = [type_param.upper()]

                    if any(t in types for t in ['CELL', 'MOBILE', 'IPHONE']):
                        temp_mobile.add(display)
                    elif any(t in types for t in ['WORK', 'BUSINESS']):
                        temp_work.add(display)
                    elif any(t in types for t in ['HOME', 'PRIVATE']):
                        temp_home.add(display)
                    elif any(t in types for t in ['FAX']):
                        temp_fax.add(display)
                    else:
                        temp_other.add(display)

                if not temp_canonical:
                    continue

                # Deduplizierung: Pruefe, ob eine der Nummern bereits in einem Kontakt existiert
                target_contact = None
                for existing in merged_contacts:
                    if existing.canonical_numbers & temp_canonical:
                        target_contact = existing
                        break

                if target_contact:
                    # Kontakt zusammenfuehren!
                    target_contact.canonical_numbers.update(temp_canonical)
                    target_contact.home_numbers.update(temp_home)
                    target_contact.work_numbers.update(temp_work)
                    target_contact.mobile_numbers.update(temp_mobile)
                    target_contact.fax_numbers.update(temp_fax)
                    target_contact.other_numbers.update(temp_other)

                    # Besseren Namen waehlen (z. B. "Max Mustermann" statt "Papa")
                    if name_quality(fn, family_name, given_name) > name_quality(target_contact.fn, target_contact.family_name, target_contact.given_name):
                        target_contact.fn = fn
                        target_contact.family_name = family_name
                        target_contact.given_name = given_name
                else:
                    new_contact = MergedContact(fn, family_name, given_name)
                    new_contact.canonical_numbers = temp_canonical
                    new_contact.home_numbers = temp_home
                    new_contact.work_numbers = temp_work
                    new_contact.mobile_numbers = temp_mobile
                    new_contact.fax_numbers = temp_fax
                    new_contact.other_numbers = temp_other
                    merged_contacts.append(new_contact)

    print(f"Kontakte aus allen Accounts geladen. Insgesamt {len(merged_contacts)} eindeutige Kontakte nach Deduplizierung.")

    # LDAP Verbindung
    ldap_user = str(config.get('ldap_user') or '').strip()
    ldap_pass = str(config.get('ldap_pass') or '').strip()

    if ldap_user and ldap_pass:
        bind_dn = f'cn={ldap_user},dc=home,dc=local'
        bind_pw = ldap_pass
    else:
        bind_dn = 'cn=admin,dc=home,dc=local'
        bind_pw = 'admin_internal'

    print(f"Verbinde mit lokalem OpenLDAP als {bind_dn}...")
    server = Server('ldap://localhost:389', get_info=ALL)
    conn = Connection(server, bind_dn, bind_pw, auto_bind=True)

    # Basis OU erstellen
    conn.add('ou=contacts,dc=home,dc=local', ['organizationalUnit'])

    synced_dns = set()
    used_cns = {}

    for c in merged_contacts:
        cn = c.fn.strip()
        count = used_cns.get(cn, 0)
        used_cns[cn] = count + 1
        unique_cn = cn if count == 0 else f"{cn} ({count + 1})"

        work_list = sorted(list(c.work_numbers))
        home_list = sorted(list(c.home_numbers))
        mobile_list = sorted(list(c.mobile_numbers))
        fax_list = sorted(list(c.fax_numbers))
        other_list = sorted(list(c.other_numbers))

        # Primary telephoneNumber: Bevorzugt Festnetz/Arbeit/Allgemein, sonst Mobil
        primary_telephones = work_list + other_list
        if not primary_telephones:
            primary_telephones = mobile_list + home_list

        escaped_cn = escape_rdn(unique_cn)
        dn = f'cn={escaped_cn},ou=contacts,dc=home,dc=local'
        synced_dns.add(dn.lower())

        attrs = {
            'objectClass': ['top', 'person', 'organizationalPerson', 'inetOrgPerson'],
            'cn': unique_cn,
            'sn': c.family_name,
            'givenName': c.given_name,
            'telephoneNumber': primary_telephones
        }
        if mobile_list:
            attrs['mobile'] = mobile_list
        if home_list:
            attrs['homePhone'] = home_list
        if fax_list:
            attrs['facsimileTelephoneNumber'] = fax_list

        if not conn.add(dn, attributes=attrs):
            mod_attrs = {
                'sn': [(MODIFY_REPLACE, [c.family_name])],
                'givenName': [(MODIFY_REPLACE, [c.given_name])],
                'telephoneNumber': [(MODIFY_REPLACE, primary_telephones)],
                'mobile': [(MODIFY_REPLACE, mobile_list if mobile_list else [])],
                'homePhone': [(MODIFY_REPLACE, home_list if home_list else [])],
                'facsimileTelephoneNumber': [(MODIFY_REPLACE, fax_list if fax_list else [])],
            }
            conn.modify(dn, mod_attrs)

    # Alte Kontakte loeschen
    try:
        conn.search('ou=contacts,dc=home,dc=local', '(objectClass=inetOrgPerson)', attributes=['dn'])
        for entry in conn.entries:
            entry_dn = str(entry.entry_dn)
            if entry_dn.lower() not in synced_dns:
                print(f"Loesche entfernten Kontakt: {entry_dn}")
                conn.delete(entry_dn)
    except Exception as e:
        print(f"Hinweis beim Bereinigen alter Kontakte: {e}")

    print("Sync erfolgreich abgeschlossen.")

if __name__ == '__main__':
    try:
        sync_contacts()
    except Exception as e:
        print(f"Kritischer Fehler beim Sync: {e}")
