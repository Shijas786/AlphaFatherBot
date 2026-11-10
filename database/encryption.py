from cryptography.fernet import Fernet
import config

_fernet_instance = None

def get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        import os
        key = config.ENCRYPTION_MASTER_KEY or os.getenv("ENCRYPTION_MASTER_KEY", "")
        if not key:
            raise ValueError(
                "ENCRYPTION_MASTER_KEY is not set in .env. "
                "Generate one using: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet_instance

def encrypt_secret(plain_text: str) -> str:
    """Encrypt a secret string into an encrypted base64 string."""
    if not plain_text:
        return ""
    f = get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_secret(cipher_text: str) -> str:
    """Decrypt an encrypted base64 string back into plain text."""
    if not cipher_text:
        return ""
    f = get_fernet()
    return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
