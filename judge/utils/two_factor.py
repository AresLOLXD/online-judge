import base64


def webauthn_encode(binary):
    return base64.urlsafe_b64encode(binary).decode('ascii').rstrip('=')


def webauthn_decode(text):
    text += '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text)
