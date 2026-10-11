"""Disposable mTLS identities and HTTPS servers for native service-action tests."""

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import http.server
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading

if __name__ == "__main__":
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class Identity:
    ca: bytes
    server_cert: bytes
    server_key: bytes
    client_p12: bytes
    password: str


def _name(common):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _builder(subject, issuer, public):
    now = datetime.datetime.now(datetime.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
    )


def _authority(common):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = _name(common)
    ca = (
        _builder(ca_name, ca_name, ca_key.public_key())
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return ca_key, ca_name, ca


def _leaf(kind: str, authority):
    ca_key, ca_name, _ = authority
    common = "localhost" if kind == "server" else "disposable-client"
    usage = ExtendedKeyUsageOID.SERVER_AUTH if kind == "server" else ExtendedKeyUsageOID.CLIENT_AUTH
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = _builder(_name(common), ca_name, key.public_key())
    if kind == "server":
        certificate = certificate.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
    certificate = certificate.add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
    return key, certificate.sign(ca_key, hashes.SHA256())


def _legacy_bundle(client_key, client, password) -> bytes:
    pem = client_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ) + client.public_bytes(serialization.Encoding.PEM)
    return subprocess.run(
        [
            "/usr/bin/openssl",
            "pkcs12",
            "-export",
            "-legacy",
            "-keypbe",
            "PBE-SHA1-3DES",
            "-certpbe",
            "PBE-SHA1-RC2-40",
            "-macalg",
            "sha1",
            "-passout",
            "env:SYNTHETIC_PASSWORD",
        ],
        input=pem,
        capture_output=True,
        timeout=15,
        check=True,
        env={"PATH": "/usr/bin:/bin", "SYNTHETIC_PASSWORD": password},
    ).stdout


def _generated_identity(common, legacy=False) -> Identity:
    authority = _authority(common)
    ca = authority[2]
    server_key, server = _leaf("server", authority)
    client_key, client = _leaf("client", authority)
    password = "disposable-password"
    bundle = pkcs12.serialize_key_and_certificates(
        b"disposable-client",
        client_key,
        client,
        [ca],
        serialization.BestAvailableEncryption(password.encode()),
    )
    if legacy:
        bundle = _legacy_bundle(client_key, client, password)
    return Identity(
        ca.public_bytes(serialization.Encoding.PEM),
        server.public_bytes(serialization.Encoding.PEM),
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        bundle,
        password,
    )


def _wire(value: Identity) -> str:
    return json.dumps(
        {
            "ca": base64.b64encode(value.ca).decode(),
            "server_cert": base64.b64encode(value.server_cert).decode(),
            "server_key": base64.b64encode(value.server_key).decode(),
            "client_p12": base64.b64encode(value.client_p12).decode(),
            "password": value.password,
        }
    )


def identity(common="Disposable Test CA", *, legacy=False) -> Identity:
    from slopmeister.session.service_actions.constants import PYTHON

    result = subprocess.run(
        [str(PYTHON), str(Path(__file__).resolve()), "--identity", common, str(int(legacy))],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    data = json.loads(result.stdout)
    return Identity(
        *(base64.b64decode(data[key]) for key in ("ca", "server_cert", "server_key", "client_p12")),
        data["password"],
    )


@dataclass
class Server:
    origin: str
    ca_path: Path
    requests: list[dict]


def _handler(callback, requests):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "peer": self.connection.getpeercert(),
                }
            )
            callback(self)

        do_POST = do_GET
        do_PUT = do_GET

        def log_message(self, *_args):
            pass

    return Handler


def _tls_server(root: Path, fixture):
    credentials, handler, require_client = fixture
    cert, key, ca = root / "server.pem", root / "server.key", root / "ca.pem"
    cert.write_bytes(credentials.server_cert)
    key.write_bytes(credentials.server_key)
    ca.write_bytes(credentials.ca)
    ca.chmod(0o644)
    server = http.server.ThreadingHTTPServer(("localhost", 0), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    context.load_verify_locations(ca)
    context.verify_mode = ssl.CERT_REQUIRED if require_client else ssl.CERT_NONE
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server, ca


@contextmanager
def https_server(credentials: Identity, callback, require_client: bool = True):
    requests = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        handler = _handler(callback, requests)
        server, ca = _tls_server(root, (credentials, handler, require_client))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield Server(f"https://localhost:{server.server_port}", ca, requests)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__" and sys.argv[1:2] == ["--identity"]:
    print(_wire(_generated_identity(sys.argv[2], legacy=sys.argv[3:4] == ["1"])))
