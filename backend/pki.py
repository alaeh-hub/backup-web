"""Identity of this PC for wireless backup: a self-signed certificate and key, plus the TLS contexts built from it.

Nothing here trusts a certificate authority. Two PCs trust each other only after pairing, by remembering each
other's certificate fingerprint (SHA-256 of the DER bytes)."""
import datetime, hashlib, os, secrets, ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def fingerprint(cert):
    """SHA-256 (hex) of a certificate given as PEM text or DER bytes."""
    der = cert if isinstance(cert, bytes) else x509.load_pem_x509_certificate(cert.encode("ascii")).public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def check_cert_pem(pem):
    """Parse a client's certificate; returns its fingerprint or raises ValueError."""
    try:
        cert = x509.load_pem_x509_certificate(pem.encode("ascii"))
        cert.public_key()
        return fingerprint(pem)
    except Exception as e:
        raise ValueError("not a valid certificate") from e


class Identity:
    """This PC's long-term key and certificate, created on first use and kept in `folder`."""

    def __init__(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        key_f, cert_f = folder / "identity.key.pem", folder / "identity.cert.pem"
        if not (key_f.exists() and cert_f.exists()):
            self._create(key_f, cert_f)
        self.key_file, self.cert_file = str(key_f), str(cert_f)
        self.cert_pem = cert_f.read_text("ascii")
        self.fp = fingerprint(self.cert_pem)

    @staticmethod
    def _create(key_f, cert_f):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ala-eh-" + secrets.token_hex(4))])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False, crl_sign=False, encipher_only=False,
                                             decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        key_f.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        try:
            os.chmod(key_f, 0o600)
        except OSError:
            pass
        cert_f.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def server_context(identity, trusted_pems):
    """TLS for the agent. A client certificate is optional at the handshake, but if one is shown it must be one of
    `trusted_pems` (the paired PCs); whether a request without one may do anything is decided by the agent itself."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(identity.cert_file, identity.key_file)
    ctx.verify_mode = ssl.CERT_OPTIONAL
    ctx.load_verify_locations(cadata=trusted_pems or identity.cert_pem)   # never empty: this PC's own certificate stands in
    return ctx


def client_context(identity=None):
    """TLS for the PC that connects. The server's certificate is not checked against a CA or a host name: the caller
    compares its fingerprint with the one remembered at pairing before sending anything."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if identity:
        ctx.load_cert_chain(identity.cert_file, identity.key_file)
    return ctx
