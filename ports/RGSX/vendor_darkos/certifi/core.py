"""
certifi.py
~~~~~~~~~~

This module returns the installation location of
/etc/ssl/certs/ca-certificates.crt or its contents.
"""

DEBIAN_CA_CERTS_PATH = '/etc/ssl/certs/ca-certificates.crt'


def where() -> str:
    return DEBIAN_CA_CERTS_PATH

def contents() -> str:
    with open(where(), "r", encoding="ascii") as data:
        return data.read()
