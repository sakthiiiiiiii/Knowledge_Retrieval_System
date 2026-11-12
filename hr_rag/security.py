"""Scopes must be assigned server-side, never inferred from a prompt."""

import secrets
from .models import Principal, Chunk


class AccessDenied(PermissionError):
    pass


def allowed(principal: Principal, payload: dict) -> bool:
    # Check tenant isolation first; matching groups must not grant access across
    # organizations.
    if payload.get("tenant_id") != principal.tenant_id:
        return False
    scopes = set(payload.get("access_scopes") or [])
    if not scopes:  # unknown permissions fail closed
        return False
    grant = (
        {"internal"}
        if (
            principal.groups
            or principal.teams
            or principal.employee_id
            or principal.admin
        )
        else set()
    )
    grant.update("group:" + x for x in principal.groups)
    grant.update("team:" + x for x in principal.teams)
    if principal.employee_id:
        grant.add("employee:" + principal.employee_id)
    if principal.admin:
        grant.add("admin")
    # Any explicitly granted scope; sensitive rows do not include 'internal'.
    return bool(scopes & grant)


def require_admin(principal):
    if not principal.admin:
        raise AccessDenied("Admin access required")


def authenticate(bearer: str, settings):
    if not bearer:
        raise AccessDenied("No bearer token")
    if settings.auth_mode == "demo":
        # Compare the demo token in constant time instead of using ordinary string
        # equality.
        if not secrets.compare_digest(bearer, settings.demo_token):
            raise AccessDenied("Invalid token")
        # Demo is an internal-only, single-user token. It cannot read restricted
        # records.
        return Principal(
            user_id="demo-user",
            tenant_id="swiftpay",
            groups=("employees",),
            acl_revision="demo",
        )
    if settings.auth_mode == "jwt":
        import jwt
        from jwt import PyJWKClient

        key = PyJWKClient(settings.jwt_jwks_url).get_signing_key_from_jwt(bearer).key

        # Verify signature, expiry, issuer and audience before trusting identity or
        # access claims.
        claims = jwt.decode(
            bearer,
            key,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        # Issuer is an enterprise-controlled identity source with authoritative ACL
        # claims.
        if not claims.get("tenant_id") or not claims.get("acl_revision"):
            raise AccessDenied("Token missing authoritative access claims")
        return Principal(
            user_id=claims["sub"],
            tenant_id=claims["tenant_id"],
            groups=tuple(claims.get("groups", [])),
            teams=tuple(claims.get("managed_teams", [])),
            employee_id=claims.get("employee_id"),
            acl_revision=str(claims["acl_revision"]),
            admin="hr_rag_admin" in claims.get("groups", []),
        )
    raise AccessDenied("Authentication not configured (set AUTH_MODE)")
