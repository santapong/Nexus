"""OAuth2/OIDC authentication for Google and GitHub.

Implements the authorization code flow:
1. GET  /api/auth/oauth/{provider}            → redirect to provider consent screen
2. GET  /api/auth/oauth/{provider}/callback    → exchange code → upsert user → JWT

Supported providers: google, github.

Security:
- Anti-CSRF: a random `state` parameter is generated on /oauth/{provider},
  persisted in Redis db:1 with a 10-minute TTL, and validated on
  /oauth/{provider}/callback before the authorization code is redeemed.
- At-rest token encryption: access and refresh tokens are Fernet-encrypted
  (`nexus.api.auth.encrypt_token`) before being written to OAuthAccount and
  decrypted on read.
- Logging: provider error bodies are NEVER logged whole — only the
  `error` / `error_description` fields are surfaced.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import structlog
from litestar import Controller, Request, get
from litestar.exceptions import ClientException, NotAuthorizedException
from litestar.response import Redirect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import AuthUser, create_access_token, encrypt_token
from nexus.core.redis.clients import redis_cache
from nexus.db.models import OAuthAccount, User, Workspace, WorkspaceMember
from nexus.settings import settings

logger = structlog.get_logger()

# ─── CSRF state token constants ─────────────────────────────────────────────

_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes
_OAUTH_STATE_KEY_PREFIX = "oauth:state:"


def _state_key(provider: str, state: str) -> str:
    """Build the Redis key for an OAuth CSRF state token."""
    return f"{_OAUTH_STATE_KEY_PREFIX}{provider}:{state}"


async def _issue_oauth_state(provider: str) -> str:
    """Generate and persist a CSRF state token for the OAuth redirect.

    Args:
        provider: OAuth provider name (used to scope the Redis key).

    Returns:
        URL-safe random token to embed as the `state` query parameter.
    """
    state = secrets.token_urlsafe(32)
    try:
        await redis_cache.set(
            _state_key(provider, state),
            "1",
            ex=_OAUTH_STATE_TTL_SECONDS,
        )
    except Exception as exc:
        # If Redis is unavailable we still issue the state, but callback
        # validation will reject it — fail closed for security.
        logger.warning("oauth_state_persist_failed", provider=provider, error=str(exc))
    return state


async def _consume_oauth_state(provider: str, state: str | None) -> bool:
    """Atomically validate and delete a CSRF state token.

    Args:
        provider: OAuth provider name.
        state: State value echoed back by the provider, or None.

    Returns:
        True only when the state was present in Redis and successfully
        deleted (single-use). False on any failure, missing/empty state,
        or Redis outage — callers must reject in that case.
    """
    if not state:
        return False
    try:
        # DEL returns the number of keys removed (1 if it existed, 0 if not).
        removed = await redis_cache.delete(_state_key(provider, state))
        return int(removed) == 1
    except Exception as exc:
        logger.warning("oauth_state_validate_failed", provider=provider, error=str(exc))
        return False


# ─── Provider configuration ─────────────────────────────────────────────────

_PROVIDER_CONFIG = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scopes": "openid email profile",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scopes": "read:user user:email",
    },
}


def _get_client_credentials(provider: str) -> tuple[str, str]:
    """Get OAuth client ID and secret for a provider.

    Args:
        provider: Provider name (google, github).

    Returns:
        Tuple of (client_id, client_secret).

    Raises:
        ValueError: If provider is not configured.
    """
    if provider == "google":
        return settings.oauth_google_client_id, settings.oauth_google_client_secret
    if provider == "github":
        return settings.oauth_github_client_id, settings.oauth_github_client_secret
    raise ValueError(f"Unknown OAuth provider: {provider}")


def _get_redirect_uri(provider: str) -> str:
    """Build the OAuth callback URI for a provider.

    Args:
        provider: Provider name.

    Returns:
        Full callback URL.
    """
    base = settings.oauth_redirect_base_url or "http://localhost:8000"
    return f"{base}/api/auth/oauth/{provider}/callback"


# ─── Response schemas ────────────────────────────────────────────────────────


class OAuthLoginResponse(BaseModel):
    """Response after successful OAuth login."""

    access_token: str
    user: AuthUser
    is_new_user: bool


# ─── Controller ──────────────────────────────────────────────────────────────


class OAuthController(Controller):
    """OAuth2/OIDC authentication endpoints."""

    path = "/auth/oauth"

    @get("/{provider:str}")
    async def oauth_redirect(self, provider: str) -> Redirect:
        """Redirect user to OAuth provider consent screen.

        Generates a single-use CSRF `state` token (32 url-safe bytes),
        persists it in Redis db:1 with a 10-minute TTL, and embeds it in
        the provider URL so the callback can verify the response was
        triggered by this server.

        Args:
            provider: OAuth provider name (google, github).

        Returns:
            Redirect response to provider authorization URL.
        """
        if provider not in _PROVIDER_CONFIG:
            return Redirect(path="/")

        config = _PROVIDER_CONFIG[provider]
        client_id, _ = _get_client_credentials(provider)

        state = await _issue_oauth_state(provider)

        params: dict[str, Any] = {
            "client_id": client_id,
            "redirect_uri": _get_redirect_uri(provider),
            "response_type": "code",
            "scope": config["scopes"],
            "state": state,
        }

        if provider == "google":
            params["access_type"] = "offline"
            params["prompt"] = "consent"

        url = f"{config['authorize_url']}?{urlencode(params)}"
        return Redirect(path=url)

    @get("/{provider:str}/callback")
    async def oauth_callback(
        self,
        provider: str,
        code: str,
        db_session: AsyncSession,
        request: Request[Any, Any, Any],
        state: str | None = None,
    ) -> OAuthLoginResponse:
        """Handle OAuth callback after user authorizes.

        Validates the CSRF `state` token (single-use, Redis-backed),
        exchanges the authorization code for tokens, fetches user info,
        and creates or links the user account. OAuth access and refresh
        tokens are Fernet-encrypted before being persisted.

        Args:
            provider: OAuth provider name.
            code: Authorization code from provider.
            db_session: Async database session.
            request: Litestar request — used for diagnostic logging only.
            state: CSRF state echoed by the provider. Must match the value
                issued by /oauth/{provider} or the request is rejected.

        Returns:
            OAuthLoginResponse with JWT token and user info.

        Raises:
            ClientException: 400 — provider unknown or CSRF state invalid.
        """
        import httpx

        if provider not in _PROVIDER_CONFIG:
            raise ClientException(detail="Unsupported OAuth provider")

        # CSRF defense — reject any callback without a matching, single-use
        # state token issued by /oauth/{provider}. Failing closed here
        # blocks attacker-initiated code injection ("login CSRF").
        if not await _consume_oauth_state(provider, state):
            logger.warning(
                "oauth_state_invalid",
                provider=provider,
                client=request.client.host if request.client else "unknown",
            )
            raise ClientException(detail="Invalid or expired OAuth state")

        config = _PROVIDER_CONFIG[provider]
        client_id, client_secret = _get_client_credentials(provider)

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _get_redirect_uri(provider),
                "grant_type": "authorization_code",
            }

            headers = {"Accept": "application/json"}
            token_resp = await client.post(config["token_url"], data=token_data, headers=headers)
            try:
                token_json = token_resp.json()
            except ValueError:
                token_json = {}
            access_token = (
                token_json.get("access_token", "") if isinstance(token_json, dict) else ""
            )

            if not access_token:
                # Never log the full provider response body — it may carry
                # tokens or PII. Surface only well-known error fields.
                logger.warning(
                    "oauth_token_exchange_failed",
                    provider=provider,
                    status_code=token_resp.status_code,
                    error_code=(
                        token_json.get("error", "unknown")
                        if isinstance(token_json, dict)
                        else "unknown"
                    ),
                    error_description=(
                        token_json.get("error_description", "")
                        if isinstance(token_json, dict)
                        else ""
                    ),
                )
                raise NotAuthorizedException(detail="OAuth token exchange failed")

            # Fetch user info
            auth_header = {"Authorization": f"Bearer {access_token}"}
            if provider == "github":
                auth_header["Accept"] = "application/json"

            userinfo_resp = await client.get(config["userinfo_url"], headers=auth_header)
            userinfo = userinfo_resp.json()

        # Extract user details based on provider
        if provider == "google":
            email = userinfo.get("email", "")
            display_name = userinfo.get("name", email.split("@")[0])
            provider_user_id = userinfo.get("id", "")
            avatar_url = userinfo.get("picture")
        elif provider == "github":
            email = userinfo.get("email", "")
            display_name = userinfo.get("name") or userinfo.get("login", "")
            provider_user_id = str(userinfo.get("id", ""))
            avatar_url = userinfo.get("avatar_url")

            # GitHub may not return email — fetch from emails endpoint
            if not email:
                async with httpx.AsyncClient() as client:
                    emails_resp = await client.get(
                        "https://api.github.com/user/emails",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Accept": "application/json",
                        },
                    )
                    emails = emails_resp.json()
                    for e in emails:
                        if e.get("primary") and e.get("verified"):
                            email = e["email"]
                            break
        else:
            email = ""
            display_name = ""
            provider_user_id = ""
            avatar_url = None

        if not email or not provider_user_id:
            logger.warning("oauth_missing_user_info", provider=provider)
            return OAuthLoginResponse(
                access_token="",
                user=AuthUser(user_id="", workspace_id="", email=""),
                is_new_user=False,
            )

        # Check if OAuth account already exists
        oauth_stmt = select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
        result = await db_session.execute(oauth_stmt)
        oauth_account = result.scalar_one_or_none()

        is_new_user = False

        user: User | None = None

        if oauth_account:
            # Existing OAuth account — get user
            user_stmt = select(User).where(User.id == oauth_account.user_id)
            user_result = await db_session.execute(user_stmt)
            user = user_result.scalar_one()

            # Update tokens (Fernet-encrypt before write — never store plaintext).
            oauth_account.access_token_encrypted = encrypt_token(access_token)
            oauth_account.refresh_token_encrypted = encrypt_token(token_json.get("refresh_token"))
            if token_json.get("expires_in"):
                from datetime import timedelta

                oauth_account.token_expires_at = datetime.now(UTC) + timedelta(
                    seconds=int(token_json["expires_in"])
                )
        else:
            # Check if user exists with same email
            user_stmt = select(User).where(User.email == email)
            user_result = await db_session.execute(user_stmt)
            user = user_result.scalar_one_or_none()

            if not user:
                # Create new user
                is_new_user = True
                user = User(
                    email=email,
                    password_hash="oauth_only",  # No password for OAuth users
                    display_name=display_name,
                )
                db_session.add(user)
                await db_session.flush()

                # Create default workspace
                slug = email.split("@")[0].lower().replace(".", "-")
                workspace = Workspace(
                    name=f"{display_name}'s Company",
                    slug=slug,
                    owner_id=str(user.id),
                )
                db_session.add(workspace)
                await db_session.flush()

                member = WorkspaceMember(
                    workspace_id=str(workspace.id),
                    user_id=str(user.id),
                    role="owner",
                )
                db_session.add(member)

            # Create OAuth account link
            expires_at = None
            if token_json.get("expires_in"):
                from datetime import timedelta

                expires_at = datetime.now(UTC) + timedelta(seconds=int(token_json["expires_in"]))

            oauth_account = OAuthAccount(
                user_id=str(user.id),
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
                display_name=display_name,
                avatar_url=avatar_url,
                # Fernet-encrypt before persisting — never store plaintext.
                access_token_encrypted=encrypt_token(access_token),
                refresh_token_encrypted=encrypt_token(token_json.get("refresh_token")),
                token_expires_at=expires_at,
            )
            db_session.add(oauth_account)

        await db_session.commit()

        if user is None:
            return OAuthLoginResponse(
                access_token="",
                user=AuthUser(user_id="", workspace_id="", email=""),
                is_new_user=False,
            )

        # Get workspace for JWT
        ws_stmt = select(Workspace).where(Workspace.owner_id == str(user.id))
        ws_result = await db_session.execute(ws_stmt)
        user_workspace = ws_result.scalar_one_or_none()
        workspace_id = str(user_workspace.id) if user_workspace else ""

        jwt_token = create_access_token(
            user_id=str(user.id),
            workspace_id=workspace_id,
            email=email,
        )

        logger.info(
            "oauth_login_success",
            provider=provider,
            user_id=str(user.id),
            is_new_user=is_new_user,
        )

        return OAuthLoginResponse(
            access_token=jwt_token,
            user=AuthUser(
                user_id=str(user.id),
                workspace_id=workspace_id,
                email=email,
            ),
            is_new_user=is_new_user,
        )
