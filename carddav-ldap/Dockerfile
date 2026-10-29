ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.3.0
FROM $BUILD_FROM

RUN apk add --no-cache \
    openldap \
    openldap-clients \
    openldap-back-mdb \
    python3 \
    py3-pip \
    jq

RUN pip3 install --break-system-packages caldav ldap3 vobject phonenumbers

COPY rootfs /

RUN chmod a+x /etc/services.d/slapd/run \
    && chmod a+x /etc/services.d/sync/run

# Das s6-overlay des Basis-Images kümmert sich um den Start der Services
