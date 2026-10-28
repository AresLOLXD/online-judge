function urlSafeBase64Decode(text) {
    return Uint8Array.from([...atob(text.replace(/_/g, '/').replace(/-/g, '+'))], x => x.charCodeAt(0));
}

function urlSafeBase64Encode(buffer) {
    return btoa(String.fromCharCode(...new Uint8Array(buffer)))
        .replace(/\//g, '_')
        .replace(/\+/g, '-')
        .replace(/=+/g, '');
}

function decodePublicKeyOptions(publicKey) {
    publicKey.challenge = urlSafeBase64Decode(publicKey.challenge);
    if (publicKey.user) {
        publicKey.user.id = urlSafeBase64Decode(publicKey.user.id);
    }
    for (const list of [publicKey.excludeCredentials, publicKey.allowCredentials]) {
        for (const descriptor of list || []) {
            descriptor.id = urlSafeBase64Decode(descriptor.id);
        }
    }
}

function registrationCredentialToJSON(credential) {
    return {
        id: credential.id,
        rawId: urlSafeBase64Encode(credential.rawId),
        type: credential.type,
        response: {
            clientDataJSON: urlSafeBase64Encode(credential.response.clientDataJSON),
            attestationObject: urlSafeBase64Encode(credential.response.attestationObject),
        },
        clientExtensionResults: credential.getClientExtensionResults(),
    };
}

function authenticationCredentialToJSON(credential) {
    const userHandle = credential.response.userHandle;
    return {
        id: credential.id,
        rawId: urlSafeBase64Encode(credential.rawId),
        type: credential.type,
        response: {
            clientDataJSON: urlSafeBase64Encode(credential.response.clientDataJSON),
            authenticatorData: urlSafeBase64Encode(credential.response.authenticatorData),
            signature: urlSafeBase64Encode(credential.response.signature),
            userHandle: userHandle ? urlSafeBase64Encode(userHandle) : null,
        },
        clientExtensionResults: credential.getClientExtensionResults(),
    };
}
