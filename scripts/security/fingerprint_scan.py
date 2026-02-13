import argparse
import base64
import hashlib
import json
import socket
import ssl
import sys
from urllib.request import Request, urlopen


SECURITY_HEADERS = [
    "content-security-policy",
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
]


def scan_http_headers(url: str, timeout: float = 10.0):
    req = Request(url, headers={"User-Agent": "ShopSquireSecScan/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        headers = {k.lower(): v for k, v in resp.getheaders()}
        missing = [h for h in SECURITY_HEADERS if h not in headers]
        present = {k: headers[k] for k in headers if k in SECURITY_HEADERS}
        server = headers.get("server")
        powered_by = headers.get("x-powered-by")
        set_cookie = headers.get("set-cookie")
        cookie_flags = {}
        if set_cookie:
            cookie_flags["has_secure"] = "secure" in set_cookie.lower()
            cookie_flags["has_httponly"] = "httponly" in set_cookie.lower()
            cookie_flags["samesite"] = (
                "none" if "samesite=none" in set_cookie.lower()
                else ("lax" if "samesite=lax" in set_cookie.lower() else ("strict" if "samesite=strict" in set_cookie.lower() else None))
            )

        return {
            "url": url,
            "present": present,
            "missing": missing,
            "server": server,
            "x_powered_by": powered_by,
            "cookie_flags": cookie_flags,
        }


def tls_cert_fingerprint(host: str, port: int = 443, timeout: float = 10.0):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
            fp_sha256 = hashlib.sha256(der).hexdigest()
            # Best-effort subject info (non-binary form)
            cert = ssock.getpeercert()
            subject = cert.get("subject")
            issuer = cert.get("issuer")
            not_before = cert.get("notBefore")
            not_after = cert.get("notAfter")
            return {
                "host": host,
                "port": port,
                "sha256_fingerprint": fp_sha256,
                "subject": subject,
                "issuer": issuer,
                "validity": {"not_before": not_before, "not_after": not_after},
            }


def ssh_hostkey_fingerprint(host: str, port: int = 22, timeout: float = 10.0):
    try:
        import paramiko  # optional
    except Exception:
        return {
            "host": host,
            "port": port,
            "error": "paramiko not installed; install to retrieve SSH host key fingerprint",
        }

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        # Connect without credentials to fetch host key; may fail on strict servers
        client.connect(hostname=host, port=port, username="", password="", timeout=timeout, allow_agent=False, look_for_keys=False)
    except Exception:
        # Even if auth fails, host key may be available via transport if handshake succeeded
        pass

    transport = client.get_transport()
    if transport is None:
        return {"host": host, "port": port, "error": "unable to establish SSH transport"}
    key = transport.get_remote_server_key()
    if key is None:
        return {"host": host, "port": port, "error": "no host key retrieved"}

    raw = key.asbytes()
    fp_sha256_b64 = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")
    return {
        "host": host,
        "port": port,
        "algorithm": key.get_name(),
        "sha256_b64": fp_sha256_b64,
    }


def main():
    parser = argparse.ArgumentParser(description="ShopSquire fingerprint and header scanner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_headers = sub.add_parser("headers", help="Scan security-related HTTP headers for a URL")
    p_headers.add_argument("url", help="Target URL (https://example.com)")

    p_tls = sub.add_parser("tls", help="Get TLS certificate fingerprint for a host")
    p_tls.add_argument("target", help="host[:port], default 443")

    p_ssh = sub.add_parser("ssh", help="Get SSH host key fingerprint for a host (requires paramiko)")
    p_ssh.add_argument("target", help="host[:port], default 22")

    args = parser.parse_args()

    if args.cmd == "headers":
        res = scan_http_headers(args.url)
        print(json.dumps(res, indent=2))
        return

    if args.cmd == "tls":
        host, port = (args.target, 443)
        if ":" in args.target:
            h, p = args.target.split(":", 1)
            host, port = h, int(p)
        res = tls_cert_fingerprint(host, port)
        print(json.dumps(res, indent=2))
        return

    if args.cmd == "ssh":
        host, port = (args.target, 22)
        if ":" in args.target:
            h, p = args.target.split(":", 1)
            host, port = h, int(p)
        res = ssh_hostkey_fingerprint(host, port)
        print(json.dumps(res, indent=2))
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
