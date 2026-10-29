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
    if len(digits) >= 3:
        return digits, clean
    return None, None

class MergedContact:
    def __init__(self, fn, family_name, given_name, account_id):
        self.fn = fn
        self.family_name = family_name
        self.given_name = given_name
        self.account_ids = {account_id}
        self.home_numbers = set()
        self.work_numbers = set()
        self.mobile_numbers = set()
        self.fax_numbers = set()
        self.other_numbers = set()
        self.canonical_numbers = set()
        self.canonical_mobile_numbers = set()

def are_names_compatible(name1, name2):
    """
    Prueft, ob zwei Kontaktnamen aehnlich genug fuer eine Zusammenfuehrung sind
    (z. B. 'Erna Müller' & 'Oma Erna', 'Max Mustermann' & 'Mustermann Max').
    """
    n1 = re.sub(r'[^\w\s]', '', name1.lower()).split()
    n2 = re.sub(r'[^\w\s]', '', name2.lower()).split()

    stopwords = {'mama', 'papa', 'mami', 'papi', 'oma', 'opa', 'mum', 'dad', 'dr', 'prof'}
    w1 = [w for w in n1 if w not in stopwords and len(w) > 1]
    w2 = [w for w in n2 if w not in stopwords and len(w) > 1]

    if not w1 and not w2:
        return True

    # Wenn mindestens ein bedeutungsvolles Wort uebereinstimmt
    if set(w1) & set(w2):
        return True

    return False

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

def extract_numbers_from_vcard(vcard, default_country="DE"):
    """
    Extrahiert alle Nummern aus der vCard, inklusive Apples gruppierter Eintraege (item1.TEL).
    """
    home = set()
    work = set()
    mobile = set()
    fax = set()
    other = set()
    canonical_all = set()
    canonical_mobile = set()

    group_labels = {}
    tel_children = []

    # getChildren() erfasst ALLE Zeilen, auch item1.TEL und item1.X-ABLabel
    for child in vcard.getChildren():
        name = child.name.upper()
        group = getattr(child, 'group', None)
        if name in ('X-ABLABEL', 'X-LABEL') and group:
            group_labels[group] = str(child.value).upper()
        elif name == 'TEL' or name.endswith('.TEL'):
            tel_children.append(child)

    for tel in tel_children:
        raw_val = getattr(tel, 'value', '')
        canonical, display = normalize_number(raw_val, default_country)
        if not canonical:
            continue

        canonical_all.add(canonical)

        types = []
        if hasattr(tel, 'params') and 'TYPE' in tel.params:
            type_param = tel.params['TYPE']
            if isinstance(type_param, list):
                types = [t.upper() for t in type_param]
            elif isinstance(type_param, str):
                types = [type_param.upper()]

        group = getattr(tel, 'group', None)
        if group and group in group_labels:
            lbl = group_labels[group]
            if any(k in lbl for k in ('CELL', 'MOBILE', 'IPHONE', 'HANDY')):
                types.append('CELL')
            elif any(k in lbl for k in ('HOME', 'PRIVAT', 'ZUHAUSE')):
                types.append('HOME')
            elif any(k in lbl for k in ('WORK', 'ARBEIT', 'GESCHÄFT', 'BÜRO')):
                types.append('WORK')
            elif 'FAX' in lbl:
                types.append('FAX')

        if any(t in types for t in ('CELL', 'MOBILE', 'IPHONE')):
            mobile.add(display)
            canonical_mobile.add(canonical)
        elif any(t in types for t in ('WORK', 'BUSINESS')):
            work.add(display)
        elif any(t in types for t in ('HOME', 'PRIVATE')):
            home.add(display)
        elif any(t in types for t in ('FAX',)):
            fax.add(display)
        else:
            other.add(display)

    return {
        'home': home,
        'work': work,
        'mobile': mobile,
        'fax': fax,
        'other': other,
        'canonical': canonical_all,
        'canonical_mobile': canonical_mobile
    }

def sync_contacts():
    config = get_ha_config()
    accounts = get_accounts(config)
    default_country = config.get('default_country', 'DE').upper().strip() or 'DE'

    if not accounts:
        print("Keine iCloud Accounts konfiguriert. Abbruch.")
        return

    print(f"Starte Sync für {len(accounts)} iCloud-Account(s) (Standardland: {default_country})...")
    merged_contacts = []
    total_raw_contacts = 0

    for acc_idx, acc in enumerate(accounts, start=1):
        user = acc['user']
        print(f"[{acc_idx}/{len(accounts)}] Verbinde mit iCloud für {user}...")
        try:
            vcard_strings = fetch_icloud_vcards(user, acc['pass'])
            print(f"  -> {len(vcard_strings)} Kontakte aus iCloud für {user} empfangen.")
            total_raw_contacts += len(vcard_strings)
        except Exception as e:
            print(f"Fehler bei Verbindung mit {user}: {e}")
            continue

        for vcard_raw in vcard_strings:
            try:
                vcard = vobject.readOne(vcard_raw)
            except Exception:
                continue

            # FN ermitteln
            fn = ""
            if hasattr(vcard, 'fn'):
                fn = str(vcard.fn.value).strip()

            family_name = getattr(vcard, 'n', fn).value.family if hasattr(vcard, 'n') else fn
            given_name = getattr(vcard, 'n', fn).value.given if hasattr(vcard, 'n') else ''
            if not fn:
                fn = f"{given_name} {family_name}".strip()
            if not fn:
                continue
            if not family_name:
                family_name = fn

            # Nummern extrahieren (unterstuetzt Apple item1.TEL)
            extracted = extract_numbers_from_vcard(vcard, default_country)
            temp_canonical = extracted['canonical']

            # Wenn dieser Kontakt keinerlei Telefonnummern besitzt, ueberspringen
            if not temp_canonical:
                continue

            # Deduplizierungs-Logik:
            # 1. Kontakte aus DEMSELBEN Account werden NIEMALS zusammengefuehrt! (Eigene Kontakte sind immer eigenstaendig)
            # 2. Kontakte aus VERSCHIEDENEN Accounts werden nur zusammengefuehrt wenn:
            #    - Gleiche Handynummer (gehoert eindeutig einer Person) ODER
            #    - Gemeinsame Nummer UND aehnlicher Name
            target_contact = None
            for existing in merged_contacts:
                if acc_idx in existing.account_ids:
                    # Aus demselben Account -> nicht deduplizieren
                    continue

                shares_mobile = bool(existing.canonical_mobile_numbers & extracted['canonical_mobile'])
                shares_any_number = bool(existing.canonical_numbers & temp_canonical)

                if shares_mobile or (shares_any_number and are_names_compatible(existing.fn, fn)):
                    target_contact = existing
                    break

            if target_contact:
                target_contact.account_ids.add(acc_idx)
                target_contact.canonical_numbers.update(temp_canonical)
                target_contact.canonical_mobile_numbers.update(extracted['canonical_mobile'])
                target_contact.home_numbers.update(extracted['home'])
                target_contact.work_numbers.update(extracted['work'])
                target_contact.mobile_numbers.update(extracted['mobile'])
                target_contact.fax_numbers.update(extracted['fax'])
                target_contact.other_numbers.update(extracted['other'])

                if name_quality(fn, family_name, given_name) > name_quality(target_contact.fn, target_contact.family_name, target_contact.given_name):
                    target_contact.fn = fn
                    target_contact.family_name = family_name
                    target_contact.given_name = given_name
            else:
                new_contact = MergedContact(fn, family_name, given_name, acc_idx)
                new_contact.canonical_numbers = temp_canonical
                new_contact.canonical_mobile_numbers = extracted['canonical_mobile']
                new_contact.home_numbers = extracted['home']
                new_contact.work_numbers = extracted['work']
                new_contact.mobile_numbers = extracted['mobile']
                new_contact.fax_numbers = extracted['fax']
                new_contact.other_numbers = extracted['other']
                merged_contacts.append(new_contact)

    print(f"Kontakte aus allen Accounts geladen ({total_raw_contacts} Rohkontakte empfangen). Insgesamt {len(merged_contacts)} Telefonbuch-Kontakte nach Deduplizierung.")

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
