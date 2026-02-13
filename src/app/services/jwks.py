import os
import json
import time
import base64
from typing import Dict, Tuple, Optional, List

try:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
except Exception:
    rsa = None
    serialization = None
    default_backend = None

try:
    import jwt
except Exception:
    jwt = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _gen_rsa_keypair() -> Tuple[bytes, Dict]:
    if rsa is None:
        raise RuntimeError("cryptography not available for RSA key generation")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = key.public_key()
    nums = pub.public_numbers()
    n = nums.n
    e = nums.e
    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": _b64url(n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")),
        "e": _b64url(e.to_bytes((e.bit_length() + 7) // 8, byteorder="big")),
    }
    return priv_pem, jwk


def _load_private_pem(path: str):
    with open(path, "rb") as f:
        return f.read()


def _pub_from_priv(priv_pem: bytes) -> Dict:
    key = serialization.load_pem_private_key(priv_pem, password=None, backend=default_backend())
    pub = key.public_key()
    nums = pub.public_numbers()
    n = nums.n
    e = nums.e
    return {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": _b64url(n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")),
        "e": _b64url(e.to_bytes((e.bit_length() + 7) // 8, byteorder="big")),
    }


def _jwks_dir() -> str:
    return os.getenv("CONNECTOR_JWKS_DIR", os.path.join(os.getcwd(), "tmp", "jwks"))


def ensure_jwks() -> str:
    """Ensure a JWKS directory and at least one active key. Returns active kid."""
    d = _jwks_dir()
    os.makedirs(d, exist_ok=True)
    kid_path = os.path.join(d, "active_kid.txt")
    # If existing keys found, keep current active
    if os.path.exists(kid_path):
        with open(kid_path, "r", encoding="utf-8") as f:
            kid = f.read().strip()
        priv_path = os.path.join(d, f"{kid}.pem")
        if os.path.exists(priv_path):
            return kid
    # Otherwise generate a new key
    priv_pem, jwk = _gen_rsa_keypair()
    kid = f"kid-{int(time.time())}"
    with open(os.path.join(d, f"{kid}.pem"), "wb") as f:
        f.write(priv_pem)
    jwk["kid"] = kid
    with open(os.path.join(d, f"{kid}.jwk.json"), "w", encoding="utf-8") as f:
        json.dump(jwk, f)
    with open(kid_path, "w", encoding="utf-8") as f:
        f.write(kid)
    return kid


def rotate_keys() -> str:
    """Generate a new RSA key and set it active. Returns new kid."""
    d = _jwks_dir()
    os.makedirs(d, exist_ok=True)
    priv_pem, jwk = _gen_rsa_keypair()
    kid = f"kid-{int(time.time())}"
    with open(os.path.join(d, f"{kid}.pem"), "wb") as f:
        f.write(priv_pem)
    jwk["kid"] = kid
    with open(os.path.join(d, f"{kid}.jwk.json"), "w", encoding="utf-8") as f:
        json.dump(jwk, f)
    with open(os.path.join(d, "active_kid.txt"), "w", encoding="utf-8") as f:
        f.write(kid)
    return kid


def _get_active_priv() -> Tuple[str, bytes]:
    kid = ensure_jwks()
    d = _jwks_dir()
    priv = _load_private_pem(os.path.join(d, f"{kid}.pem"))
    return kid, priv


def jwks_document() -> Dict:
    d = _jwks_dir()
    keys = []
    for name in os.listdir(d):
        if name.endswith(".jwk.json"):
            try:
                with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                    jwk = json.load(f)
                    keys.append(jwk)
            except Exception:
                continue
    return {"keys": keys}


def issue_token(sub: str, scopes: List[str], ttl_seconds: int = 3600, issuer: Optional[str] = None, audience: Optional[str] = None) -> str:
    if jwt is None:
        raise RuntimeError("PyJWT not available")
    kid, priv = _get_active_priv()
    now = int(time.time())
    payload = {
        "sub": sub,
        "iat": now,
        "exp": now + int(ttl_seconds or 3600),
        "scope": " ".join(scopes or []),
    }
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience
    headers = {"kid": kid, "alg": "RS256"}
    token = jwt.encode(payload, priv, algorithm="RS256", headers=headers)
    # PyJWT returns str for RS256
    return token


def _load_pubkey_for_kid(kid: str):
    d = _jwks_dir()
    jwk_path = os.path.join(d, f"{kid}.jwk.json")
    if not os.path.exists(jwk_path):
        return None
    with open(jwk_path, "r", encoding="utf-8") as f:
        jwk = json.load(f)
    # Build PEM from JWK
    n_b = base64.urlsafe_b64decode(jwk["n"] + "==")
    e_b = base64.urlsafe_b64decode(jwk["e"] + "==")
    n = int.from_bytes(n_b, byteorder="big")
    e = int.from_bytes(e_b, byteorder="big")
    pub_numbers = rsa.RSAPublicNumbers(e, n)
    pub_key = pub_numbers.public_key(default_backend())
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pub_pem


def verify_token(token: str) -> Tuple[bool, Dict]:
    if jwt is None:
        return False, {"error": "jwt_unavailable"}
    # Extract kid from header
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
    except Exception:
        return False, {"error": "bad_header"}
    try:
        pub_pem = _load_pubkey_for_kid(kid) if kid else None
        if not pub_pem:
            # Try current active
            cur_kid, priv = _get_active_priv()
            pub_pem = _pub_from_priv(priv)
            # If we only have JWK fields, issue a failure
            return False, {"error": "kid_not_found"}
        payload = jwt.decode(token, pub_pem, algorithms=["RS256"], options={"verify_aud": False})
        return True, payload
    except Exception as exc:
        return False, {"error": "verify_failed", "detail": str(exc)}
