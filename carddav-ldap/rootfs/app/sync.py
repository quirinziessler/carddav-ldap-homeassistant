import os
import json
import caldav
from ldap3 import Server, Connection, ALL, MODIFY_REPLACE

def get_ha_config():
    with open('/data/options.json') as f:
        return json.load(f)

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
    
    print("Verbinde mit lokalem OpenLDAP...")
    server = Server('ldap://localhost:389', get_info=ALL)
    conn = Connection(server, 'cn=admin,dc=home,dc=local', 'admin', auto_bind=True)
    
    # Basis OU erstellen, falls nicht vorhanden
    conn.add('ou=contacts,dc=home,dc=local', ['organizationalUnit'])
    
    print("Synchronisiere Kontakte...")
    for book in addressbooks:
        for contact in book.contacts():
            vcard = contact.vobject_instance
            if hasattr(vcard, 'fn') and hasattr(vcard, 'tel'):
                cn = vcard.fn.value
                dn = f'cn={cn},ou=contacts,dc=home,dc=local'
                
                # Attribute für Gigaset (inetOrgPerson)
                family_name = getattr(vcard, 'n', cn).value.family if hasattr(vcard, 'n') else cn
                given_name = getattr(vcard, 'n', cn).value.given if hasattr(vcard, 'n') else ''
                
                # Leere Nachnamen abfangen (LDAP benötigt sn zwingend)
                if not family_name:
                    family_name = cn

                telephone_numbers = [t.value for t in getattr(vcard, 'contents', {}).get('tel', [])]
                
                attrs = {
                    'objectClass': ['top', 'person', 'organizationalPerson', 'inetOrgPerson'],
                    'sn': family_name,
                    'givenName': given_name,
                    'telephoneNumber': telephone_numbers
                }
                
                if not conn.add(dn, attributes=attrs):
                    conn.modify(dn, {'telephoneNumber': [(MODIFY_REPLACE, telephone_numbers)]})

    print("Sync erfolgreich abgeschlossen.")

if __name__ == '__main__':
    try:
        sync_contacts()
    except Exception as e:
        print(f"Kritischer Fehler beim Sync: {e}")
