class DomainError(Exception):
    pass


class PlaybackError(DomainError):
    pass


class AuthorizationError(DomainError):
    pass

