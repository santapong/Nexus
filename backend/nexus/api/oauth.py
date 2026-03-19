"""OAuth2/OIDC authentication for Google and GitHub.

Implements the authorization code flow:
1. GET  /api/auth/oauth/{provider}            → redirect to provider consent screen
2. GET  /api/auth/oauth/{provider}/callback    → exchange code → upsert user → JWT

Supported providers: google, github.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

import structlog
from litestar import Controller, get
from litestar.response import Redirect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import AuthUser, create_access_token
from nexus.db.models import OAuthAccount, User, Workspace, WorkspaceMember
from nexus.settings import settings

logger = structlog.get_logger()


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

        Args:
            provider: OAuth provider name (google, github).

        Returns:
            Redirect response to provider authorization URL.
        """
        if provider not in _PROVIDER_CONFIG:
            return Redirect(path="/")

        config = _PROVIDER_CONFIG[provider]
        client_id, _ = _get_client_credentials(provider)

        params = {
            "client_id": client_id,
            "redirect_uri": _get_redirect_uri(provider),
            "response_type": "code",
            "scope": config["scopes"],
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
    ) -> OAuthLoginResponse:
        """Handle OAuth callback after user authorizes.

        Exchanges the authorization code for tokens, fetches user info,
        and creates or links the user account.

        Args:
            provider: OAuth provider name.
            code: Authorization code from provider.
            db_session: Async database session.

        Returns:
            OAuthLoginResponse with JWT token and user info.
        """
        import httpx

        if provider not in _PROVIDER_CONFIG:
            return OAuthLoginResponse(
                access_token="",
                user=AuthUser(user_id="", workspace_id="", email=""),
                is_new_user=False,
            )

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
            token_json = token_resp.json()
            access_token = token_json.get("access_token", "")

            if not access_token:
                logger.warning(
                    "oauth_token_exchange_failed",
                    provider=provider,
                    error=token_json.get("error", "unknown"),
                )
                return OAuthLoginResponse(
                    access_token="",
                    user=AuthUser(user_id="", workspace_id="", email=""),
                    is_new_user=False,
                )

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

        if oauth_account:
            # Existing OAuth account — get user
            user_stmt = select(User).where(User.id == oauth_account.user_id)
            user_result = await db_session.execute(user_stmt)
            user = user_result.scalar_one()

            # Update tokens
            oauth_account.access_token_encrypted = access_token
            oauth_account.refresh_token_encrypted = token_json.get("refresh_token")
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
                access_token_encrypted=access_token,
                refresh_token_encrypted=token_json.get("refresh_token"),
                token_expires_at=expires_at,
            )
            db_session.add(oauth_account)

        await db_session.commit()

        # Get workspace for JWT
        ws_stmt = select(Workspace).where(Workspace.owner_id == str(user.id))
        ws_result = await db_session.execute(ws_stmt)
        workspace = ws_result.scalar_one_or_none()
        workspace_id = str(workspace.id) if workspace else ""

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
