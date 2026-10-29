import os
import re
import json
import socket
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import requests
from requests.auth import HTTPBasicAuth
import vobject
import phonenumbers
from ldap3 import Server, Connection, ALL, MODIFY_REPLACE
try:
    from ldap3.utils.dn import escape_rdn
except ImportError:
    def escape_rdn(s):
        for c in (',', '+', '=', '"', '\\', '<', '>', ';'):
            s = s.replace(c, f'\\{c}')
        return s

# Zwinge Python auf IPv4, um "OSError(90, Message too large)" durch Docker/MTU/IPv6-Probleme zu verhindern
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(*args, **kwargs):
    responses = _orig_getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4 if ipv4 else responses
socket.getaddrinfo = _getaddrinfo_ipv4

def get_ha_config():
    with open('/data/options.json') as f:
        return json.load(f)

def get_accounts(config):
    accounts = []
    if 'accounts' in config and isinstance(config['accounts'], list):
        for acc in config['accounts']:
            user = (acc.get('user') or '').strip()
            password = (acc.get('pass') or '').strip()
            if user and password:
                accounts.append({'user': user, 'pass': password})

    if not accounts:
        user = (config.get('icloud_user') or '').strip()
        password = (config.get('icloud_pass') or '').strip()
        if user and password:
            accounts.append({'user': user, 'pass': password})

    return accounts

def fetch_icloud_vcards(user, password):
    """
    Laedt alle vCards via nativem CardDAV (RFC 6352) von Apple iCloud herunter.
    """
    session = requests.Session()
    session.auth = HTTPBasicAuth(user, password)
    session.headers.update({
        'Content-Type': 'text/xml; charset=utf-8',
        'User-Agent': 'CardDAV/1.0 (HomeAssistant)'
    })

    base_url = "https://contacts.icloud.com"

    # Schritt 1: Principal Discovery
    propfind_principal = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:">
        <d:prop>
            <d:current-user-principal/>
        </d:prop>
    </d:propfind>"""

    resp = session.request('PROPFIND', f"{base_url}/", data=propfind_principal, headers={'Depth': '0'}, timeout=30)
    if resp.status_code not in (200, 207):
        raise Exception(f"Principal Discovery fehlgeschlagen ({resp.status_code}): {resp.text[:200]}")

    root = ET.fromstring(resp.content)
    principal_href = None
    for elem in root.iter():
        if elem.tag.endswith('current-user-principal'):
            for child in elem.iter():
                if child.tag.endswith('href') and child.text:
                    principal_href = child.text.strip()
                    break
        if principal_href:
            break

    if not principal_href:
        raise Exception("current-user-principal nicht in Apple-Antwort gefunden.")

    principal_url = principal_href if principal_href.startswith('http') else f"{base_url}{principal_href}"

    # Schritt 2: addressbook-home-set ermitteln
    propfind_homeset = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
        <d:prop>
            <c:addressbook-home-set/>
        </d:prop>
    </d:propfind>"""

    resp2 = session.request('PROPFIND', principal_url, data=propfind_homeset, headers={'Depth': '0'}, timeout=30)
    if resp2.status_code not in (200, 207):
        raise Exception(f"Home-Set Discovery fehlgeschlagen ({resp2.status_code}): {resp2.text[:200]}")

    root2 = ET.fromstring(resp2.content)
    homeset_href = None
    for elem in root2.iter():
        if elem.tag.endswith('addressbook-home-set'):
            for child in elem.iter():
                if child.tag.endswith('href') and child.text:
                    homeset_href = child.text.strip()
                    break
        if homeset_href:
            break

    if not homeset_href:
        raise Exception("addressbook-home-set nicht in Apple-Antwort gefunden.")

    homeset_url = homeset_href if homeset_href.startswith('http') else f"{base_url}{homeset_href}"

    # Schritt 3: Adressbuecher in addressbook-home-set finden
    propfind_books = """<?xml version="1.0" encoding="utf-8" ?>
    <d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
        <d:prop>
            <d:resourcetype/>
            <d:displayname/>
        </d:prop>
    </d:propfind>"""

    resp3 = session.request('PROPFIND', homeset_url, data=propfind_books, headers={'Depth': '1'}, timeout=30)
    if resp3.status_code not in (200, 207):
        raise Exception(f"Adressbuch-Suche fehlgeschlagen ({resp3.status_code}): {resp3.text[:200]}")

    root3 = ET.fromstring(resp3.content)
    p = urlparse(homeset_url)
    host_base = f"{p.scheme}://{p.netloc}"

    addressbook_urls = []
    for resp_elem in root3.iter():
        if resp_elem.tag.endswith('response'):
            is_addressbook = False
            href_val = None
            for child in resp_elem.iter():
                if child.tag.endswith('href') and child.text and not href_val:
                    href_val = child.text.strip()
                if child.tag.endswith('addressbook'):
                    is_addressbook = True
            if is_addressbook and href_val:
                full_book_url = href_val if href_val.startswith('http') else f"{host_base}{href_val}"
                addressbook_urls.append(full_book_url)

    if not addressbook_urls:
        card_fallback = homeset_url if homeset_url.endswith('/') else f"{homeset_url}/"
        addressbook_urls.append(f"{card_fallback}card/")

    # Schritt 4: vCards via REPORT addressbook-query laden
    report_query = """<?xml version="1.0" encoding="utf-8" ?>
    <c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
        <d:prop>
            <d:getetag/>
            <c:address-data/>
        </d:prop>
    </c:addressbook-query>"""

    vcard_strings = []
    for book_url in addressbook_urls:
        resp4 = session.request('REPORT', book_url, data=report_query, headers={'Depth': '1'}, timeout=60)
        if resp4.status_code in (200, 207):
            root4 = ET.fromstring(resp4.content)
            for child in root4.iter():
                if child.tag.endswith('address-data') and child.text:
                    vcard_strings.append(child.text)
        else:
            print(f"REPORT auf {book_url} lieferte Status {resp4.status_code}")

    return vcard_strings

def normalize_number(raw_num, default_country="DE"):
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

    if fam_clean and giv_clean and fam_clean != fn_clean and giv_clean != fn_clean:
        score += 100
    elif fam_clean and fam_clean != fn_clean:
        score += 40

    score += min(len(fn_clean), 30)

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
    merged_contacts = []

    for acc_idx, acc in enumerate(accounts, start=1):
        user = acc['user']
        print(f"[{acc_idx}/{len(accounts)}] Verbinde mit iCloud für {user}...")
        try:
            vcard_strings = fetch_icloud_vcards(user, acc['pass'])
            print(f"  -> {len(vcard_strings)} Kontakte aus iCloud für {user} empfangen.")
        except Exception as e:
            print(f"Fehler bei Verbindung mit {user}: {e}")
            continue

        for vcard_raw in vcard_strings:
            try:
                vcard = vobject.readOne(vcard_raw)
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

            target_contact = None
            for existing in merged_contacts:
                if existing.canonical_numbers & temp_canonical:
                    target_contact = existing
                    break

            if target_contact:
                target_contact.canonical_numbers.update(temp_canonical)
                target_contact.home_numbers.update(temp_home)
                target_contact.work_numbers.update(temp_work)
                target_contact.mobile_numbers.update(temp_mobile)
                target_contact.fax_numbers.update(temp_fax)
                target_contact.other_numbers.update(temp_other)

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

    # Bereinige in iCloud geloeschte Kontakte aus LDAP (Attribut 'cn' statt 'dn' anfordern)
    try:
        conn.search('ou=contacts,dc=home,dc=local', '(objectClass=inetOrgPerson)', attributes=['cn'])
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
