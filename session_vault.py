"""Encrypt/decrypt the Divar login so it can sit in GitHub's cache safely.

    python session_vault.py newkey                 print a new SESSION_KEY
    python session_vault.py encrypt <in> <out>     uses $SESSION_KEY
    python session_vault.py decrypt <in> <out>
    python session_vault.py export                 divar_session.json -> divar_session.secret.txt
                                                   (the DIVAR_SESSION_ENC secret for the first run)
"""
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

import config


def _fernet():
    key = os.environ.get("SESSION_KEY") or Path("session_key.txt").read_text().strip()
    return Fernet(key.encode())


cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "newkey":
    Path("session_key.txt").write_text(Fernet.generate_key().decode())
    print("New key written to session_key.txt (the SESSION_KEY secret)")
elif cmd == "encrypt":
    Path(sys.argv[3]).write_bytes(_fernet().encrypt(Path(sys.argv[2]).read_bytes()))
elif cmd == "decrypt":
    Path(sys.argv[3]).write_bytes(_fernet().decrypt(Path(sys.argv[2]).read_bytes()))
elif cmd == "export":
    Path("divar_session.secret.txt").write_bytes(_fernet().encrypt(config.DIVAR_SESSION.read_bytes()))
    print("Encrypted login written to divar_session.secret.txt (the DIVAR_SESSION_ENC secret)")
else:
    raise SystemExit(__doc__)
