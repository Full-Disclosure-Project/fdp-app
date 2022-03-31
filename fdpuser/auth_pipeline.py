from social_core.exceptions import AuthForbidden
import logging

logger = logging.getLogger(__name__)


def auth_allowed(backend, details, response, *args, **kwargs):
    if not backend.auth_allowed(response, details):
        logger.error("scammonyroot")
        raise AuthForbidden(backend)
