"""Pure-Python local root CA and leaf cert generation.

Produces a self-signed root CA and a leaf cert signed by it, suitable for
terminating TLS at `https://localhost:8443` (Phase 1 light mode) or
`https://api.anthropic.com` when the hostname is hijacked via hosts file
(Phase 2 strict mode).
"""
from __future__ import annotations

import datetime as dt
import ipaddress
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY_SIZE = 2048
_ROOT_VALIDITY = dt.timedelta(days=365 * 10)
_LEAF_VALIDITY = dt.timedelta(days=365)


@dataclass
class RootCa:
    cert_pem: bytes
    key_pem: bytes
    _key: rsa.RSAPrivateKey
    _cert: x509.Certificate


@dataclass
class LeafCert:
    cert_pem: bytes
    key_pem: bytes


def _serialize_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def generate_root(*, common_name: str = "piighost local CA") -> RootCa:
    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    subject = x509.Name(
        [x509.NameAttribute(x509.NameOID.COMMON_NAME, common_name)]
    )
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + _ROOT_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                key_cert_sign=True,
                crl_sign=True,
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return RootCa(
        cert_pem=cert.public_bytes(serialization.Encoding.PEM),
        key_pem=_serialize_key(key),
        _key=key,
        _cert=cert,
    )


def generate_leaf(root: RootCa, *, hostnames: list[str]) -> LeafCert:
    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)

    sans: list[x509.GeneralName] = []
    for h in hostnames:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            sans.append(x509.DNSName(h))

    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, hostnames[0])]))
        .issuer_name(root._cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + _LEAF_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(root._key, hashes.SHA256())
    )
    return LeafCert(
        cert_pem=cert.public_bytes(serialization.Encoding.PEM),
        key_pem=_serialize_key(key),
    )
