from datetime import date, datetime
from uuid import UUID

import bcrypt
import psycopg2

from app.db.connection import get_db_connection_context
from app.models.user_model import (
    DeleteUserRequestBody, SearchUsersCursor, SearchUsersQuery,
    UpdateProfileRequestBody, UpdateUserRequestBody,
)
from app.services.errors import ServiceError
from app.utils.pagination import decode_cursor, encode_cursor


def _serialize(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _serialize_media(media, owner_id):
    if (
        not media
        or media.get("status") != "READY"
        or media.get("deleted_at")
        or str(media.get("owner_id")) != str(owner_id)
    ):
        return None
    result = {
        field: media.get(field)
        for field in (
            "id", "content_type", "byte_size", "width", "height", "status", "created_at"
        )
    }
    result.update({"download_url": None, "url_expires_at": None})
    return _serialize(result)


def _get_account(cur, user_id):
    cur.execute(
        """
        SELECT u.id, u.email, u.username, u.status,
               u.email_verified_at IS NOT NULL AS email_verified, u.created_at,
               to_jsonb(p) AS profile,
               to_jsonb(avatar) AS avatar, to_jsonb(cover) AS cover
        FROM public.users u
        LEFT JOIN public.user_profiles p ON p.user_id = u.id
        LEFT JOIN public.media_assets avatar ON avatar.id = p.avatar_media_id
        LEFT JOIN public.media_assets cover ON cover.id = p.cover_media_id
        WHERE u.id = %(user_id)s AND u.deleted_at IS NULL
        """,
        {"user_id": user_id},
    )
    account = cur.fetchone()
    if account is None:
        return None

    profile = account.pop("profile") or {}
    fields = ("bio", "birthday", "gender", "location", "website")
    result = {field: profile.get(field) for field in fields}
    result.update({
        "user_id": str(account["id"]),
        "display_name": profile.get("display_name") or account["username"],
        "joined_at": account["created_at"],
        "updated_at": profile.get("updated_at") or account["created_at"],
    })
    for name in ("avatar", "cover"):
        result[name] = _serialize_media(account.pop(name), account["id"])
    account["profile"] = result
    return _serialize(account)


def get_current_user(user_id):
    """Return the current account and its safe profile representation."""
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            account = _get_account(cur, user_id)

    if account is None:
        raise ServiceError({"message": "User not found"}, 404)
    if account["status"] != "ACTIVE":
        raise ServiceError({"message": "User not found or inactive"}, 403)

    return account


def update_current_user(user_id, body: UpdateUserRequestBody):
    """Update the username and return the account in one transaction."""
    try:
        with get_db_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.users SET username = %(username)s
                    WHERE id = %(user_id)s AND deleted_at IS NULL AND status = 'ACTIVE'
                    RETURNING id
                    """,
                    {"username": body.username, "user_id": user_id},
                )
                if cur.fetchone() is None:
                    raise ServiceError({"message": "User not found or inactive"}, 403)
                account = _get_account(cur, user_id)
            conn.commit()

        return account
    except psycopg2.errors.UniqueViolation as error:
        raise ServiceError(
            {"error": "USERNAME_UNAVAILABLE", "message": "Username is unavailable"},
            409,
        ) from error


def delete_current_user(user_id, body: DeleteUserRequestBody):
    """Verify the password, soft delete the account and revoke its tokens."""
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT password_hash FROM public.users
                WHERE id = %(user_id)s AND deleted_at IS NULL AND status = 'ACTIVE'
                FOR UPDATE
                """,
                {"user_id": user_id},
            )
            user = cur.fetchone()
            if user is None:
                raise ServiceError({"message": "User not found or inactive"}, 403)
            password_hash = user["password_hash"]
            try:
                valid_password = password_hash and bcrypt.checkpw(
                    body.current_password.encode("utf-8"),
                    password_hash.encode("utf-8"),
                )
            except ValueError:
                valid_password = False
            if not valid_password:
                raise ServiceError(
                    {"error": "CURRENT_PASSWORD_INVALID", "message": "Current password is invalid"},
                    403,
                )
            cur.execute(
                """
                UPDATE public.users
                SET status = 'DELETED', deleted_at = NOW(),
                    token_version = token_version + 1
                WHERE id = %(user_id)s
                """,
                {"user_id": user_id},
            )
            cur.execute(
                """
                UPDATE public.refresh_tokens rt SET revoked_at = NOW()
                FROM public.auth_sessions s
                WHERE rt.session_id = s.id AND s.user_id = %(user_id)s
                  AND rt.revoked_at IS NULL
                """,
                {"user_id": user_id},
            )
            cur.execute(
                """
                UPDATE public.auth_sessions SET revoked_at = NOW()
                WHERE user_id = %(user_id)s AND revoked_at IS NULL
                """,
                {"user_id": user_id},
            )
            cur.execute(
                """
                UPDATE public.account_tokens SET revoked_at = NOW()
                WHERE user_id = %(user_id)s
                  AND used_at IS NULL AND revoked_at IS NULL
                """,
                {"user_id": user_id},
            )
        conn.commit()


def _get_public_profile(cur, viewer_id, lookup_sql, lookup_params):
    """Read the public profile using an internal, parameterized lookup condition."""
    cur.execute(
        f"""
        SELECT u.id, u.username, u.status, u.deleted_at,
               COALESCE(p.display_name, u.username) AS display_name,
               p.bio, p.gender, p.location, p.website, u.created_at AS joined_at,
               to_jsonb(avatar) AS avatar, to_jsonb(cover) AS cover,
               f.status AS friendship_status,
               f.requested_by_id AS friendship_requester_id,
               EXISTS (
                   SELECT 1 FROM public.user_blocks b
                   WHERE (b.blocker_id = %(viewer_id)s AND b.blocked_id = u.id)
                      OR (b.blocker_id = u.id AND b.blocked_id = %(viewer_id)s)
               ) AS is_blocked,
               EXISTS (
                   SELECT 1 FROM public.user_restrictions r
                   WHERE r.restrictor_id = %(viewer_id)s AND r.restricted_id = u.id
               ) AS restricted_by_me
        FROM public.users u
        LEFT JOIN public.user_profiles p ON p.user_id = u.id
        LEFT JOIN public.media_assets avatar ON avatar.id = p.avatar_media_id
        LEFT JOIN public.media_assets cover ON cover.id = p.cover_media_id
        LEFT JOIN public.friendships f
          ON f.user_low_id = LEAST(%(viewer_id)s::uuid, u.id)
         AND f.user_high_id = GREATEST(%(viewer_id)s::uuid, u.id)
        WHERE {lookup_sql}
        """,
        {"viewer_id": viewer_id, **lookup_params},
    )
    user = cur.fetchone()

    if (
        user is None
        or user["status"] != "ACTIVE"
        or user["deleted_at"] is not None
        or user["is_blocked"]
    ):
        raise ServiceError({"message": "User not found"}, 404)

    relationship_state = "NONE"
    if str(user["id"]) == str(viewer_id):
        relationship_state = "SELF"
    elif user["friendship_status"] == "ACCEPTED":
        relationship_state = "FRIENDS"
    elif user["friendship_status"] == "PENDING":
        relationship_state = (
            "OUTGOING_PENDING"
            if str(user["friendship_requester_id"]) == str(viewer_id)
            else "INCOMING_PENDING"
        )

    profile = {
        field: user[field]
        for field in ("id", "username", "display_name", "bio", "gender",
                      "location", "website", "joined_at", "restricted_by_me")
    }
    profile.update({
        "avatar": _serialize_media(user["avatar"], user["id"]),
        "cover": _serialize_media(user["cover"], user["id"]),
        "relationship_state": relationship_state,
    })
    return _serialize(profile)


def get_user_profile(viewer_id, user_id):
    """Return a public profile visible to the authenticated viewer."""
    viewer_id = str(UUID(str(viewer_id)))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            return _get_public_profile(
                cur, viewer_id, "u.id = %(user_id)s", {"user_id": user_id}
            )


def get_user_by_username(viewer_id, username):
    """Look up a public profile by its case-insensitive username."""
    viewer_id = str(UUID(str(viewer_id)))
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            return _get_public_profile(
                cur, viewer_id, "LOWER(u.username) = LOWER(%(username)s)",
                {"username": username},
            )


def _serialize_user_summary(user):
    avatar = _serialize_media(user.get("avatar"), user["id"])
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar_url": avatar["download_url"] if avatar else None,
    }


def search_users(viewer_id, query: SearchUsersQuery):
    """Search active, unblocked accounts with stable, query-bound pagination."""
    filters = {"q": query.q}
    position = decode_cursor(
        query.cursor, "users-search", viewer_id, filters, SearchUsersCursor
    )
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.username, LOWER(u.username) AS sort_username,
                       COALESCE(p.display_name, u.username) AS display_name,
                       to_jsonb(avatar) AS avatar
                FROM public.users u
                LEFT JOIN public.user_profiles p ON p.user_id = u.id
                LEFT JOIN public.media_assets avatar ON avatar.id = p.avatar_media_id
                WHERE u.status = 'ACTIVE' AND u.deleted_at IS NULL
                  AND (strpos(LOWER(u.username), %(q)s) > 0
                       OR strpos(LOWER(p.display_name), %(q)s) > 0)
                  AND NOT EXISTS (
                      SELECT 1 FROM public.user_blocks b
                      WHERE (b.blocker_id = %(viewer_id)s AND b.blocked_id = u.id)
                         OR (b.blocker_id = u.id AND b.blocked_id = %(viewer_id)s)
                  )
                  AND (
                      %(after_username)s::text IS NULL
                      OR (LOWER(u.username), u.id) >
                         (%(after_username)s::text, %(after_id)s::uuid)
                  )
                ORDER BY LOWER(u.username) ASC, u.id ASC
                LIMIT %(fetch_limit)s
                """,
                {
                    "viewer_id": viewer_id, "q": query.q,
                    "after_username": position.username if position else None,
                    "after_id": str(position.id) if position else None,
                    "fetch_limit": query.limit + 1,
                },
            )
            rows = cur.fetchall()
    has_more = len(rows) > query.limit
    rows = rows[:query.limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(
            "users-search", viewer_id, filters,
            {"username": last["sort_username"], "id": str(last["id"])},
        )
    return {
        "data": [_serialize_user_summary(row) for row in rows],
        "pagination": {
            "limit": query.limit, "has_more": has_more, "next_cursor": next_cursor,
        },
    }


def update_current_profile(user_id, body: UpdateProfileRequestBody):
    """Apply only supplied profile fields and validate media in the same transaction."""
    fields = [name for name in UpdateProfileRequestBody.model_fields
              if name in body.model_fields_set]
    values = body.model_dump(exclude_unset=True)
    with get_db_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username FROM public.users
                WHERE id = %(user_id)s AND status = 'ACTIVE' AND deleted_at IS NULL
                FOR UPDATE
                """,
                {"user_id": user_id},
            )
            user = cur.fetchone()
            if user is None:
                raise ServiceError({"message": "User not found or inactive"}, 403)

            media_ids = sorted({
                str(values[field])
                for field in ("avatar_media_id", "cover_media_id")
                if values.get(field) is not None
            })
            for media_id in media_ids:
                cur.execute(
                    """
                    SELECT status FROM public.media_assets
                    WHERE id = %(media_id)s AND owner_id = %(user_id)s
                      AND deleted_at IS NULL
                    FOR SHARE
                    """,
                    {"media_id": media_id, "user_id": user_id},
                )
                media = cur.fetchone()
                if media is None:
                    raise ServiceError({"error": "NOT_FOUND", "message": "Media not found"}, 404)
                if media["status"] != "READY":
                    raise ServiceError(
                        {"error": "MEDIA_NOT_READY", "message": "Media is not ready"}, 409
                    )

            # Older registrations may have an account without a profile row.
            cur.execute(
                """
                INSERT INTO public.user_profiles (user_id, display_name)
                VALUES (%(user_id)s, %(display_name)s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                {"user_id": user_id, "display_name": user["username"]},
            )
            assignments = ", ".join(f"{field} = %({field})s" for field in fields)
            params = {
                key: str(value) if isinstance(value, UUID) else value
                for key, value in values.items()
            }
            params["user_id"] = user_id
            cur.execute(
                f"UPDATE public.user_profiles SET {assignments} WHERE user_id = %(user_id)s",
                params,
            )
            account = _get_account(cur, user_id)
            profile = account["profile"]
        conn.commit()
    return profile

