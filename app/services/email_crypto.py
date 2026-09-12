import base64
import hashlib
import hmac
import json
import secrets
from app.config import settings

def _get_encryption_key() -> bytes:
    raw_secret = getattr(settings, "MAIL_ENCRYPTION_SECRET", None) or settings.JWT_SECRET or "gu-dsw-fallback-secret-key-2026"
    return hashlib.sha256(raw_secret.encode("utf-8")).digest()

def encrypt_refresh_token(plain_token: str) -> str:
    """
    Encrypts an OAuth refresh token securely with authenticated encryption.
    """
    if not plain_token:
        return ""
    key = _get_encryption_key()
    iv = secrets.token_bytes(16)
    plain_bytes = plain_token.encode("utf-8")
    
    # Generate keystream blocks using HMAC-SHA256 counter mode
    blocks = []
    for i in range((len(plain_bytes) + 31) // 32):
        block_key = hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
        blocks.append(block_key)
    keystream = b"".join(blocks)[:len(plain_bytes)]
    
    ciphertext = bytes(a ^ b for a, b in zip(plain_bytes, keystream))
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
    
    payload = {
        "v": 1,
        "iv": base64.b64encode(iv).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
        "mac": base64.b64encode(mac).decode("ascii")
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

def decrypt_refresh_token(enc_token: str) -> str:
    """
    Decrypts an authenticated OAuth refresh token.
    Raises ValueError if ciphertext is altered or key is invalid.
    """
    if not enc_token:
        return ""
    try:
        key = _get_encryption_key()
        raw_json = base64.urlsafe_b64decode(enc_token.encode("ascii")).decode("utf-8")
        data = json.loads(raw_json)
        
        iv = base64.b64decode(data["iv"])
        ciphertext = base64.b64decode(data["ct"])
        mac = base64.b64decode(data["mac"])
        
        expected_mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise ValueError("Integrity check failed. Token may have been tampered or encryption key changed.")
            
        blocks = []
        for i in range((len(ciphertext) + 31) // 32):
            block_key = hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
            blocks.append(block_key)
        keystream = b"".join(blocks)[:len(ciphertext)]
        
        return bytes(a ^ b for a, b in zip(ciphertext, keystream)).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Failed to decrypt refresh token: {str(e)}")
