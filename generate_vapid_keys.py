"""Generate a fresh VAPID key pair locally. Keep the private key secret."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,NoEncryption,PublicFormat

key=ec.generate_private_key(ec.SECP256R1())
public=key.public_key().public_bytes(Encoding.X962,PublicFormat.UncompressedPoint)
private=key.private_numbers().private_value.to_bytes(32,"big")
b64=lambda data:base64.urlsafe_b64encode(data).rstrip(b"=").decode()
print("GitHub variable VAPID_PUBLIC_KEY:",b64(public))
print("GitHub secret VAPID_PRIVATE_KEY:",b64(private))
print("Never commit or publish the private key.")
