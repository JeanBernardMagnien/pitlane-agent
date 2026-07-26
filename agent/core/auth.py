import jwt as pyjwt
from flask import abort, request

from core import config_store


LOCAL_ADDRESSES = ('127.0.0.1', '::1')


def require_local():
    """Garde pour les routes de contrôle purement locales (capacity profiler),
    jamais appelées par le Hub. Contrôle applicatif uniquement : HTTP_CFG['host']
    reste 0.0.0.0 par défaut, le socket est donc joignable depuis le réseau — ne
    pas se fier à request.remote_addr comme unique rempart si un durcissement
    réseau (bind localhost dédié) devient nécessaire plus tard."""
    if request.remote_addr not in LOCAL_ADDRESSES:
        abort(403, 'Accès local uniquement')


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
