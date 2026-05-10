import jwt as pyjwt
from flask import abort, request

import config_store


def require_jwt():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        abort(401, 'Token manquant')

    token = auth_header[7:]
    try:
        pyjwt.decode(
            token,
            config_store.AUTH_CFG['jwt_secret'],
            algorithms=[config_store.AUTH_CFG['jwt_algorithm']],
            leeway=30,
        )
    except pyjwt.ExpiredSignatureError:
        abort(401, 'Token expiré')
    except pyjwt.InvalidTokenError:
        abort(401, 'Token invalide')
