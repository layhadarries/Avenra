"""Generate an operator-held queue key file, never print private key material."""
import argparse
import hashlib
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def generate(path):
    path=Path(path).expanduser()
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as output:
        output.write(pem); output.flush(); os.fsync(output.fileno())
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(public).hexdigest()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    identifier=generate(args.output)
    print('Private key saved without overwrite. Public key identifier:',identifier)
