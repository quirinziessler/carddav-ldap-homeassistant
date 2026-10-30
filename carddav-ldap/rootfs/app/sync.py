import os
import re
import csv
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

def deduplicate_ldap_telephones(numbers_list):
    seen_keys = set()
    result = []
    for num in numbers_list:
        clean_str = str(num or '').strip()
        if not clean_str:
            continue
        key = re.sub(r'[\s\-]', '', clean_str)
        if key not in seen_keys:
            seen_keys.add(key)
            result.append(clean_str)
    return result

def get_number_variants(raw_num, default_country="DE"):
    clean = str(raw_num or '').strip()
    if not clean:
        return None, []

    canonical_e164 = None
    variants = []

    try:
        parsed = phonenumbers.parse(clean, default_country)
        if phonenumbers.is_possible_number(parsed):
            canonical_e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            intl_display = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            nat_display = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)

            variants.append(intl_display)
            variants.append(nat_display)

            if canonical_e164.startswith('+'):
                zerozero = '00' + intl_display[1:]
                variants.append(zerozero)
    except Exception:
        pass

    digits = re.sub(r'[^\d+]', '', clean)
    if len(digits) >= 3:
        if not canonical_e164:
            canonical_e164 = digits
        variants.append(clean)

    clean_variants = deduplicate_ldap_telephones(variants)
    return canonical_e164, clean_variants

class MergedContact:
    def __init__(self, fn, family_name, given_name, account_id, email=""):
        self.fn = fn
        self.family_name = family_name
        self.given_name = given_name
        self.email = email
        self.account_ids = {account_id}
        self.home_numbers = []
        self.work_numbers = []
        self.mobile_numbers = []
        self.fax_numbers = []
        self.other_numbers = []
        self.canonical_numbers = set()
        self.canonical_mobile_numbers = set()
        self.canonical_mobile = []
        self.canonical_home = []
        self.canonical_work = []
        self.canonical_other = []

def are_names_compatible(name1, name2):
    n1 = re.sub(r'[^\w\s]', '', name1.lower()).split()
    n2 = re.sub(r'[^\w\s]', '', name2.lower()).split()

    stopwords = {'mama', 'papa', 'mami', 'papi', 'oma', 'opa', 'mum', 'dad', 'dr', 'prof'}
    w1 = [w for w in n1 if w not in stopwords and len(w) > 1]
    w2 = [w for w in n2 if w not in stopwords and len(w) > 1]

    if not w1 and not w2:
        return True

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
    home = []
    work = []
    mobile = []
    fax = []
    other = []
    canonical_all = set()
    canonical_mobile = set()

    canonical_mobile_list = []
    canonical_home_list = []
    canonical_work_list = []
    canonical_other_list = []

    group_labels = {}
    tel_children = []
    email = ""

    for child in vcard.getChildren():
        name = child.name.upper()
        group = getattr(child, 'group', None)
        if name in ('X-ABLABEL', 'X-LABEL') and group:
            group_labels[group] = str(child.value).upper()
        elif name == 'TEL' or name.endswith('.TEL'):
            tel_children.append(child)
        elif name == 'EMAIL' or name.endswith('.EMAIL'):
            if not email:
                email = str(child.value).strip()

    for tel in tel_children:
        raw_val = getattr(tel, 'value', '')
        canonical, variants = get_number_variants(raw_val, default_country)
        if not canonical or not variants:
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
            mobile.extend(variants)
            canonical_mobile.add(canonical)
            canonical_mobile_list.append(canonical)
        elif any(t in types for t in ('WORK', 'BUSINESS')):
            work.extend(variants)
            canonical_work_list.append(canonical)
        elif any(t in types for t in ('HOME', 'PRIVATE')):
            home.extend(variants)
            canonical_home_list.append(canonical)
        elif any(t in types for t in ('FAX',)):
            fax.extend(variants)
        else:
            other.extend(variants)
            canonical_other_list.append(canonical)

    return {
        'home': deduplicate_ldap_telephones(home),
        'work': deduplicate_ldap_telephones(work),
        'mobile': deduplicate_ldap_telephones(mobile),
        'fax': deduplicate_ldap_telephones(fax),
        'other': deduplicate_ldap_telephones(other),
        'canonical': canonical_all,
        'canonical_mobile': canonical_mobile,
        'canonical_mobile_list': canonical_mobile_list,
        'canonical_home_list': canonical_home_list,
        'canonical_work_list': canonical_work_list,
        'canonical_other_list': canonical_other_list,
        'email': email
    }

def sync_unifi_talk(merged_contacts, config):
    """
    Synchronisiert Kontakte via REST-API direkt in UniFi Talk (Console / UDM / Cloud Key).
    """
    if not config.get('unifi_talk_enabled', False):
        return

    host = str(config.get('unifi_talk_host') or '').strip()
    user = str(config.get('unifi_talk_user') or '').strip()
    password = str(config.get('unifi_talk_pass') or '').strip()
    list_name = str(config.get('unifi_talk_contact_list') or 'iCloud').strip()
    verify_ssl = bool(config.get('unifi_talk_verify_ssl', False))

    if not host or not user or not password:
        print("UniFi Talk Sync ist aktiviert, aber Host, Benutzername oder Passwort fehlen.")
        return

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if host.startswith('http://') or host.startswith('https://'):
        base_url = host.rstrip('/')
    else:
        base_url = f"https://{host.rstrip('/')}"

    print(f"Verbinde mit UniFi Console unter {base_url}...")
    session = requests.Session()

    # 1. Login an UniFi OS
    login_url = f"{base_url}/api/auth/login"
    login_payload = {
        'username': user,
        'password': password,
        'remember': True
    }
    try:
        resp = session.post(login_url, json=login_payload, verify=verify_ssl, timeout=15)
    except Exception as e:
        print(f"Fehler beim Verbindungsaufbau zu UniFi ({base_url}): {e}")
        return

    if resp.status_code != 200:
        print(f"UniFi OS Login fehlgeschlagen: {resp.status_code} {resp.text}")
        return

    csrf_token = resp.headers.get('X-Csrf-Token') or resp.headers.get('x-csrf-token') or resp.cookies.get('csrf_token') or resp.cookies.get('TOKEN')
    headers = {'X-Csrf-Token': csrf_token} if csrf_token else {}
    print("Erfolgreich an UniFi OS angemeldet.")

    # 2. Kontaktliste finden oder erstellen
    try:
        resp = session.get(f"{base_url}/proxy/talk/api/contact_list", verify=verify_ssl, timeout=15, headers=headers)
        if resp.status_code != 200:
            print(f"Fehler beim Abrufen der UniFi Talk Kontaktlisten: {resp.status_code} {resp.text}")
            return
        contact_lists = resp.json() or []
    except Exception as e:
        print(f"Fehler beim Abfragen von UniFi Talk Kontaktlisten: {e}")
        return

    target_list = None
    for cl in contact_lists:
        if cl.get('name') == list_name:
            target_list = cl
            break

    if not target_list:
        print(f"Erstelle neue UniFi Talk Kontaktliste '{list_name}'...")
        create_resp = session.post(
            f"{base_url}/proxy/talk/api/contact_list",
            json={'name': list_name, 'contacts': []},
            headers=headers,
            verify=verify_ssl,
            timeout=15
        )
        if create_resp.status_code not in (200, 201):
            print(f"Fehler beim Erstellen der Kontaktliste '{list_name}': {create_resp.status_code} {create_resp.text}")
            return
        resp = session.get(f"{base_url}/proxy/talk/api/contact_list", verify=verify_ssl, timeout=15, headers=headers)
        contact_lists = resp.json() or []
        for cl in contact_lists:
            if cl.get('name') == list_name:
                target_list = cl
                break

    if not target_list or 'id' not in target_list:
        print(f"Konnte ID der UniFi Talk Kontaktliste '{list_name}' nicht ermitteln.")
        return

    contact_list_id = target_list['id']
    print(f"Verwende UniFi Talk Kontaktliste '{list_name}' (ID: {contact_list_id}).")

    # 3. Alte Kontakte aus dieser Kontaktliste bereinigen
    try:
        resp = session.get(f"{base_url}/proxy/talk/api/contacts", verify=verify_ssl, timeout=30, headers=headers)
        if resp.status_code == 200:
            existing_contacts = resp.json() or []
            ids_to_delete = []
            for ec in existing_contacts:
                c_lists = ec.get('contactLists', [])
                in_this_list = False
                for item in c_lists:
                    if (isinstance(item, dict) and item.get('id') == contact_list_id) or (item == contact_list_id):
                        in_this_list = True
                        break
                if in_this_list and 'uuid' in ec:
                    ids_to_delete.append(ec['uuid'])

            if ids_to_delete:
                print(f"Lösche {len(ids_to_delete)} bestehende Kontakte aus Liste '{list_name}'...")
                for i in range(0, len(ids_to_delete), 50):
                    chunk = ids_to_delete[i:i + 50]
                    session.post(
                        f"{base_url}/proxy/talk/api/contact/delete",
                        json={'ids': chunk},
                        headers=headers,
                        verify=verify_ssl,
                        timeout=30
                    )
    except Exception as e:
        print(f"Hinweis beim Bereinigen alter UniFi Talk Kontakte: {e}")

    # 4. Kontakte für UniFi Talk formatieren
    unifi_contacts_payload = []
    for c in merged_contacts:
        numbers = []
        seen_dids = set()

        for m in list(dict.fromkeys(c.canonical_mobile)):
            if m not in seen_dids:
                numbers.append({'did': m, 'label': 'mobile'})
                seen_dids.add(m)
        for h in list(dict.fromkeys(c.canonical_home)):
            if h not in seen_dids:
                numbers.append({'did': h, 'label': 'home'})
                seen_dids.add(h)
        for w in list(dict.fromkeys(c.canonical_work)):
            if w not in seen_dids:
                numbers.append({'did': w, 'label': 'work'})
                seen_dids.add(w)
        for o in list(dict.fromkeys(c.canonical_other)):
            if o not in seen_dids:
                numbers.append({'did': o, 'label': 'other'})
                seen_dids.add(o)

        if not numbers and c.canonical_numbers:
            for num in list(dict.fromkeys(sorted(list(c.canonical_numbers)))):
                if num not in seen_dids:
                    numbers.append({'did': num, 'label': 'other'})
                    seen_dids.add(num)

        if not numbers:
            continue

        first_n = c.given_name.strip() if c.given_name else c.fn.strip()
        last_n = c.family_name.strip() if c.given_name else ''

        entry = {
            'first_name': first_n,
            'last_name': last_n,
            'numbers': numbers,
            'contactLists': [contact_list_id],
            'invalid_field': False
        }
        if getattr(c, 'email', None):
            entry['email'] = c.email

        unifi_contacts_payload.append(entry)

    # 5. Kontakte in Batches nach UniFi Talk pushen
    print(f"Übertrage {len(unifi_contacts_payload)} Kontakte nach UniFi Talk in Liste '{list_name}'...")
    success_count = 0
    for i in range(0, len(unifi_contacts_payload), 50):
        chunk = unifi_contacts_payload[i:i + 50]
        payload = {
            'contactListId': contact_list_id,
            'contacts': chunk
        }
        save_resp = session.post(
            f"{base_url}/proxy/talk/api/contacts",
            json=payload,
            headers=headers,
            verify=verify_ssl,
            timeout=30
        )
        if save_resp.status_code in (200, 201):
            success_count += len(chunk)
        else:
            print(f"Fehler beim Speichern eines Batches in UniFi Talk: {save_resp.status_code} {save_resp.text[:200]}")

    print(f"UniFi Talk Sync abgeschlossen: {success_count} von {len(unifi_contacts_payload)} Kontakten in Liste '{list_name}' synchronisiert.")

def export_unifi_csv(merged_contacts):
    """
    Schreibt ein aktuelles UniFi Talk CSV-Backup nach /share und /config.
    """
    target_dirs = []
    if os.path.isdir('/share'):
        target_dirs.append('/share')
    if os.path.isdir('/config'):
        target_dirs.append('/config')

    if not target_dirs:
        return

    header = ['first_name', 'last_name', 'company', 'job_title', 'email', 'mobile_number', 'home_number', 'work_number', 'fax_number', 'other_number']

    for d in target_dirs:
        csv_file = os.path.join(d, 'unifi_talk_contacts.csv')
        try:
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                for c in merged_contacts:
                    first_n = c.given_name.strip() if c.given_name else c.fn.strip()
                    last_n = c.family_name.strip() if c.given_name else ''
                    mob = c.canonical_mobile[0] if c.canonical_mobile else ''
                    hom = c.canonical_home[0] if c.canonical_home else ''
                    wrk = c.canonical_work[0] if c.canonical_work else ''
                    oth = c.canonical_other[0] if c.canonical_other else ''
                    if not (mob or hom or wrk or oth) and c.canonical_numbers:
                        mob = list(c.canonical_numbers)[0]

                    writer.writerow([
                        first_n,
                        last_n,
                        '',
                        '',
                        getattr(c, 'email', ''),
                        mob,
                        hom,
                        wrk,
                        '',
                        oth
                    ])
            print(f"UniFi Talk CSV-Datei erfolgreich aktualisiert: {csv_file}")
        except Exception as e:
            print(f"Hinweis beim Schreiben von {csv_file}: {e}")

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

            extracted = extract_numbers_from_vcard(vcard, default_country)
            temp_canonical = extracted['canonical']

            if not temp_canonical:
                continue

            target_contact = None
            for existing in merged_contacts:
                if acc_idx in existing.account_ids:
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
                target_contact.home_numbers.extend(extracted['home'])
                target_contact.work_numbers.extend(extracted['work'])
                target_contact.mobile_numbers.extend(extracted['mobile'])
                target_contact.fax_numbers.extend(extracted['fax'])
                target_contact.other_numbers.extend(extracted['other'])
                target_contact.canonical_mobile.extend(extracted['canonical_mobile_list'])
                target_contact.canonical_home.extend(extracted['canonical_home_list'])
                target_contact.canonical_work.extend(extracted['canonical_work_list'])
                target_contact.canonical_other.extend(extracted['canonical_other_list'])
                if not getattr(target_contact, 'email', None) and extracted.get('email'):
                    target_contact.email = extracted['email']

                if name_quality(fn, family_name, given_name) > name_quality(target_contact.fn, target_contact.family_name, target_contact.given_name):
                    target_contact.fn = fn
                    target_contact.family_name = family_name
                    target_contact.given_name = given_name
            else:
                new_contact = MergedContact(fn, family_name, given_name, acc_idx, email=extracted.get('email', ''))
                new_contact.canonical_numbers = temp_canonical
                new_contact.canonical_mobile_numbers = extracted['canonical_mobile']
                new_contact.home_numbers = extracted['home']
                new_contact.work_numbers = extracted['work']
                new_contact.mobile_numbers = extracted['mobile']
                new_contact.fax_numbers = extracted['fax']
                new_contact.other_numbers = extracted['other']
                new_contact.canonical_mobile = extracted['canonical_mobile_list']
                new_contact.canonical_home = extracted['canonical_home_list']
                new_contact.canonical_work = extracted['canonical_work_list']
                new_contact.canonical_other = extracted['canonical_other_list']
                merged_contacts.append(new_contact)

    print(f"Kontakte aus allen Accounts geladen ({total_raw_contacts} Rohkontakte). Insgesamt {len(merged_contacts)} Telefonbuch-Kontakte nach Deduplizierung.")

    # 1. OpenLDAP Synchronisation (fuer Gigaset / VoIP)
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

    # Basis Domain dc=home,dc=local anlegen
    conn.add('dc=home,dc=local', ['top', 'dcObject', 'organization'], {'dc': 'home', 'o': 'Home'})
    if conn.result.get('description') not in ('success', 'entryAlreadyExists'):
        print(f"Initialisierung dc=home,dc=local: {conn.result}")

    # OU ou=contacts,dc=home,dc=local anlegen
    conn.add('ou=contacts,dc=home,dc=local', ['top', 'organizationalUnit'], {'ou': 'contacts'})
    if conn.result.get('description') not in ('success', 'entryAlreadyExists'):
        print(f"Initialisierung ou=contacts,dc=home,dc=local: {conn.result}")

    synced_dns = set()
    used_cns = {}
    success_count = 0

    print(f"Schreibe {len(merged_contacts)} Kontakte in LDAP...")
    for c in merged_contacts:
        cn = c.fn.strip()
        count = used_cns.get(cn, 0)
        used_cns[cn] = count + 1
        unique_cn = cn if count == 0 else f"{cn} ({count + 1})"

        work_list = deduplicate_ldap_telephones(c.work_numbers)
        home_list = deduplicate_ldap_telephones(c.home_numbers)
        mobile_list = deduplicate_ldap_telephones(c.mobile_numbers)
        fax_list = deduplicate_ldap_telephones(c.fax_numbers)
        other_list = deduplicate_ldap_telephones(c.other_numbers)

        primary_telephones = deduplicate_ldap_telephones(work_list + other_list)
        if not primary_telephones:
            primary_telephones = deduplicate_ldap_telephones(mobile_list + home_list)

        escaped_cn = escape_rdn(unique_cn)
        dn = f'cn={escaped_cn},ou=contacts,dc=home,dc=local'
        synced_dns.add(dn.lower())

        attrs = {
            'objectClass': ['top', 'person', 'organizationalPerson', 'inetOrgPerson'],
            'cn': unique_cn,
            'sn': c.family_name if c.family_name else unique_cn,
            'telephoneNumber': primary_telephones
        }
        if c.given_name and c.given_name.strip():
            attrs['givenName'] = c.given_name.strip()
        if mobile_list:
            attrs['mobile'] = mobile_list
        if home_list:
            attrs['homePhone'] = home_list
        if fax_list:
            attrs['facsimileTelephoneNumber'] = fax_list

        if conn.add(dn, attributes=attrs):
            success_count += 1
        else:
            if conn.result.get('description') == 'entryAlreadyExists':
                mod_attrs = {
                    'sn': [(MODIFY_REPLACE, [c.family_name if c.family_name else unique_cn])],
                    'telephoneNumber': [(MODIFY_REPLACE, primary_telephones)],
                    'mobile': [(MODIFY_REPLACE, mobile_list if mobile_list else [])],
                    'homePhone': [(MODIFY_REPLACE, home_list if home_list else [])],
                    'facsimileTelephoneNumber': [(MODIFY_REPLACE, fax_list if fax_list else [])],
                }
                if c.given_name and c.given_name.strip():
                    mod_attrs['givenName'] = [(MODIFY_REPLACE, [c.given_name.strip()])]
                else:
                    mod_attrs['givenName'] = [(MODIFY_REPLACE, [])]

                if conn.modify(dn, mod_attrs):
                    success_count += 1
                else:
                    print(f"Fehler beim Aktualisieren von {dn}: {conn.result}")
            else:
                print(f"Fehler beim Hinzufügen von {dn}: {conn.result}")

    print(f"LDAP-Bestand: {success_count} von {len(merged_contacts)} Kontakten erfolgreich in OpenLDAP hinterlegt.")

    # Bereinige in iCloud geloeschte Kontakte aus LDAP
    try:
        conn.search('ou=contacts,dc=home,dc=local', '(objectClass=inetOrgPerson)', attributes=['cn'])
        for entry in conn.entries:
            entry_dn = str(entry.entry_dn)
            if entry_dn.lower() not in synced_dns:
                print(f"Loesche entfernten Kontakt aus LDAP: {entry_dn}")
                conn.delete(entry_dn)
    except Exception as e:
        print(f"Hinweis beim Bereinigen alter Kontakte in LDAP: {e}")

    # 2. UniFi Talk Synchronisation (optional)
    try:
        sync_unifi_talk(merged_contacts, config)
    except Exception as e:
        print(f"Fehler bei UniFi Talk Synchronisation: {e}")

    # 3. CSV Export (in /share und /config fuer manuelle Uploads oder Backups)
    try:
        export_unifi_csv(merged_contacts)
    except Exception as e:
        print(f"Hinweis beim Schreiben der UniFi CSV: {e}")

    print("Sync erfolgreich abgeschlossen.")

if __name__ == '__main__':
    try:
        sync_contacts()
    except Exception as e:
        print(f"Kritischer Fehler beim Sync: {e}")
