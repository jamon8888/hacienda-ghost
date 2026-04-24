from __future__ import annotations

from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from piighost.install.ca import LeafCert, RootCa, generate_leaf, generate_root


def test_root_ca_has_expected_subject() -> None:
    root = generate_root(common_name="piighost local CA")
    cert = x509.load_pem_x509_certificate(root.cert_pem)
    cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    assert cn == "piighost local CA"


def test_root_ca_is_self_signed_and_ca() -> None:
    root = generate_root(common_name="piighost local CA")
    cert = x509.load_pem_x509_certificate(root.cert_pem)
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    assert cert.issuer == cert.subject


def test_leaf_cert_signed_by_root() -> None:
    root = generate_root(common_name="piighost local CA")
    leaf = generate_leaf(root, hostnames=["localhost", "127.0.0.1"])
    leaf_cert = x509.load_pem_x509_certificate(leaf.cert_pem)
    root_cert = x509.load_pem_x509_certificate(root.cert_pem)
    # issuer of leaf == subject of root
    assert leaf_cert.issuer == root_cert.subject
    # SAN contains localhost
    san = leaf_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    names = [g.value for g in san]
    assert "localhost" in names


def test_root_and_leaf_writable_to_disk(tmp_path: Path) -> None:
    root = generate_root(common_name="piighost local CA")
    leaf = generate_leaf(root, hostnames=["localhost"])
    (tmp_path / "ca.pem").write_bytes(root.cert_pem)
    (tmp_path / "ca.key").write_bytes(root.key_pem)
    (tmp_path / "leaf.pem").write_bytes(leaf.cert_pem)
    (tmp_path / "leaf.key").write_bytes(leaf.key_pem)
    # Sanity: files parse
    x509.load_pem_x509_certificate((tmp_path / "ca.pem").read_bytes())
    serialization.load_pem_private_key((tmp_path / "ca.key").read_bytes(), password=None)
