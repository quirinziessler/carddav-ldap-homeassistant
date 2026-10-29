import os
import json
import caldav
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

def extract_phone_numbers(vcard):
    home_numbers = []
    work_numbers = []
    mobile_numbers = []
    fax_numbers = []
    other_numbers = []

    tel_entries = getattr(vcard, 'contents', {}).get('tel', [])
    for tel in tel_entries:
        raw_val = getattr(tel, 'value', '')
        if not raw_val:
            continue
        num = str(raw_val).strip()
        if not num:
            continue

        types = []
        if hasattr(tel, 'params') and 'TYPE' in tel.params:
            type_param = tel.params['TYPE']
            if isinstance(type_param, list):
                types = [t.upper() for t in type_param]
            elif isinstance(type_param, str):
                types = [type_param.upper()]

        is_mobile = any(t in types for t in ['CELL', 'MOBILE', 'IPHONE'])
        is_home = any(t in types for t in ['HOME', 'PRIVATE'])
        is_work = any(t in types for t in ['WORK', 'BUSINESS'])
        is_fax = any(t in types for t in ['FAX'])

        if is_mobile:
            mobile_numbers.append(num)
        elif is_work:
            work_numbers.append(num)
        elif is_home:
            home_numbers.append(num)
        elif is_fax:
            fax_numbers.append(num)
        else:
            other_numbers.append(num)

    return {
        'home': home_numbers,
        'work': work_numbers,
        'mobile': mobile_numbers,
        'fax': fax_numbers,
        'other': other_numbers
    }

def sync_contacts():
    config = get_ha_config()
    print("Verbinde mit iCloud CardDAV...")
    
    client = caldav.DAVClient(
        url="https://contacts.icloud.com",
        username=config['icloud_user'],
        password=config['icloud_pass']
    )
    principal = client.principal()
    addressbooks = principal.addressbooks()

    # LDAP Credentials ermitteln
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

    # Basis OU erstellen, falls nicht vorhanden
    conn.add('ou=contacts,dc=home,dc=local', ['organizationalUnit'])

    print("Synchronisiere Kontakte...")
    synced_dns = set()
    used_cns = {}

    for book in addressbooks:
        for contact in book.contacts():
            vcard = contact.vobject_instance
            if hasattr(vcard, 'fn') and hasattr(vcard, 'tel'):
                cn = str(vcard.fn.value).strip()
                if not cn:
                    continue

                # Name handling
                family_name = getattr(vcard, 'n', cn).value.family if hasattr(vcard, 'n') else cn
                given_name = getattr(vcard, 'n', cn).value.given if hasattr(vcard, 'n') else ''

                if not family_name:
                    family_name = cn

                phone_data = extract_phone_numbers(vcard)
                work_numbers = phone_data['work']
                home_numbers = phone_data['home']
                mobile_numbers = phone_data['mobile']
                fax_numbers = phone_data['fax']
                other_numbers = phone_data['other']

                # Wenn gar keine Nummern vorhanden sind, Eintrag ueberspringen
                if not (work_numbers or home_numbers or mobile_numbers or fax_numbers or other_numbers):
                    continue

                # primary telephoneNumber: bevorzugt Arbeitsnummer / Allgemeine Nummer, sonst Handy / Privat
                primary_telephones = list(dict.fromkeys(work_numbers + other_numbers))
                if not primary_telephones:
                    primary_telephones = list(dict.fromkeys(mobile_numbers + home_numbers))

                # Kollisionen bei gleichen Namen verhindern
                count = used_cns.get(cn, 0)
                used_cns[cn] = count + 1
                unique_cn = cn if count == 0 else f"{cn} ({count + 1})"

                escaped_cn = escape_rdn(unique_cn)
                dn = f'cn={escaped_cn},ou=contacts,dc=home,dc=local'
                synced_dns.add(dn.lower())

                attrs = {
                    'objectClass': ['top', 'person', 'organizationalPerson', 'inetOrgPerson'],
                    'cn': unique_cn,
                    'sn': family_name,
                    'givenName': given_name,
                    'telephoneNumber': primary_telephones
                }
                if mobile_numbers:
                    attrs['mobile'] = mobile_numbers
                if home_numbers:
                    attrs['homePhone'] = home_numbers
                if fax_numbers:
                    attrs['facsimileTelephoneNumber'] = fax_numbers

                if not conn.add(dn, attributes=attrs):
                    mod_attrs = {
                        'sn': [(MODIFY_REPLACE, [family_name])],
                        'givenName': [(MODIFY_REPLACE, [given_name])],
                        'telephoneNumber': [(MODIFY_REPLACE, primary_telephones)],
                        'mobile': [(MODIFY_REPLACE, mobile_numbers if mobile_numbers else [])],
                        'homePhone': [(MODIFY_REPLACE, home_numbers if home_numbers else [])],
                        'facsimileTelephoneNumber': [(MODIFY_REPLACE, fax_numbers if fax_numbers else [])],
                    }
                    conn.modify(dn, mod_attrs)

    # Bereinige in iCloud geloeschte Kontakte aus LDAP
    try:
        conn.search('ou=contacts,dc=home,dc=local', '(objectClass=inetOrgPerson)', attributes=['dn'])
        for entry in conn.entries:
            entry_dn = str(entry.entry_dn)
            if entry_dn.lower() not in synced_dns:
                print(f"Loesche entfernten Kontakt aus LDAP: {entry_dn}")
                conn.delete(entry_dn)
    except Exception as e:
        print(f"Hinweis beim Bereinigen alter Kontakte: {e}")

    print("Sync erfolgreich abgeschlossen.")

if __name__ == '__main__':
    try:
        sync_contacts()
    except Exception as e:
        print(f"Kritischer Fehler beim Sync: {e}")
