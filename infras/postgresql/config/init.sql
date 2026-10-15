-- Social network schema, PostgreSQL 16+.
-- Run once in a fresh namespace: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f social_schema.sql
-- No existing schema/tables are dropped. Business authorization remains in the backend.
BEGIN;
CREATE SCHEMA social;

-- ACCOUNT / AUTH -------------------------------------------------------------
CREATE TABLE public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(254) NOT NULL,
    username VARCHAR(30) NOT NULL,
    password_hash TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    email_verified_at TIMESTAMPTZ,
    token_version INTEGER NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT users_email_format CHECK (email = btrim(email) AND length(email) >= 3),
    CONSTRAINT users_username_format CHECK (username ~ '^[A-Za-z0-9_]{3,30}$'),
    CONSTRAINT users_password_hash_nonempty CHECK (length(password_hash) > 0),
    CONSTRAINT users_status_valid CHECK (status IN ('ACTIVE','LOCKED','DISABLED','DELETED')),
    CONSTRAINT users_token_version_nonnegative CHECK (token_version >= 0),
    CONSTRAINT users_deleted_state CHECK ((status = 'DELETED') = (deleted_at IS NOT NULL))
);

CREATE TABLE public.user_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES public.users(id)
        ON DELETE CASCADE,

    provider TEXT NOT NULL,

    provider_user_id TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT statement_timestamp(),

    CONSTRAINT user_identities_provider_check
        CHECK (provider IN ('google', 'github', 'apple')),

    CONSTRAINT user_identities_provider_uq
        UNIQUE (provider, provider_user_id)
);

CREATE UNIQUE INDEX users_email_ci_uq ON public.users (lower(email));
CREATE UNIQUE INDEX users_username_ci_uq ON public.users (lower(username));

CREATE TABLE public.auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    user_agent TEXT,
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT auth_sessions_expiry CHECK (expires_at > created_at)
);
CREATE INDEX auth_sessions_user_active_idx ON public.auth_sessions (user_id, created_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX auth_sessions_expiry_idx ON public.auth_sessions (expires_at);

-- Opaque, random refresh tokens. Store SHA-256 bytes of the opaque value, never the raw value.
-- JWT revocation uses session id (sid), not a digest of the access JWT.
CREATE TABLE public.refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.auth_sessions(id) ON DELETE CASCADE,
    token_hash BYTEA NOT NULL UNIQUE,
    previous_token_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT refresh_tokens_hash_length CHECK (octet_length(token_hash) = 32),
    CONSTRAINT refresh_tokens_expiry CHECK (expires_at > created_at),
    CONSTRAINT refresh_tokens_not_self CHECK (previous_token_id IS DISTINCT FROM id),
    CONSTRAINT refresh_tokens_session_id_uq UNIQUE (session_id, id),
    CONSTRAINT refresh_tokens_previous_fk FOREIGN KEY (session_id, previous_token_id)
        REFERENCES public.refresh_tokens(session_id, id) ON DELETE SET NULL (previous_token_id)
);
CREATE UNIQUE INDEX refresh_tokens_one_live_per_session_uq ON public.refresh_tokens (session_id)
    WHERE used_at IS NULL AND revoked_at IS NULL;
CREATE INDEX refresh_tokens_expiry_idx ON public.refresh_tokens (expires_at);
CREATE INDEX refresh_tokens_previous_idx ON public.refresh_tokens (session_id, previous_token_id);

CREATE TABLE public.account_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash BYTEA NOT NULL UNIQUE,
    target_email VARCHAR(254) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT account_tokens_purpose CHECK (purpose IN ('VERIFY_EMAIL','RESET_PASSWORD')),
    CONSTRAINT account_tokens_hash_length CHECK (octet_length(token_hash) = 32),
    CONSTRAINT account_tokens_expiry CHECK (expires_at > created_at)
);
CREATE INDEX account_tokens_user_live_idx ON public.account_tokens (user_id, purpose)
    WHERE used_at IS NULL AND revoked_at IS NULL;
CREATE INDEX account_tokens_expiry_idx ON public.account_tokens (expires_at);

-- MEDIA / PROFILE -------------------------------------------------------------
CREATE TABLE public.media_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    storage_provider TEXT NOT NULL DEFAULT 'S3',
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    byte_size BIGINT NOT NULL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'UPLOADING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT media_storage_provider CHECK (storage_provider IN ('S3','MINIO')),
    CONSTRAINT media_object_nonempty CHECK (length(bucket) > 0 AND length(object_key) > 0),
    CONSTRAINT media_object_uq UNIQUE (storage_provider, bucket, object_key),
    CONSTRAINT media_byte_size CHECK (byte_size > 0),
    CONSTRAINT media_dimensions CHECK ((width IS NULL OR width > 0) AND (height IS NULL OR height > 0)),
    CONSTRAINT media_status_valid CHECK (status IN ('UPLOADING','READY','FAILED','DELETED')),
    CONSTRAINT media_deleted_state CHECK ((status = 'DELETED') = (deleted_at IS NOT NULL))
);
CREATE INDEX media_assets_owner_idx ON public.media_assets (owner_id, created_at DESC);

CREATE TABLE public.user_profiles (
    user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    display_name VARCHAR(100) NOT NULL,
    bio VARCHAR(500),
    birthday DATE,
    gender VARCHAR(32),
    location VARCHAR(150),
    website VARCHAR(2048),
    avatar_media_id UUID REFERENCES public.media_assets(id) ON DELETE SET NULL,
    cover_media_id UUID REFERENCES public.media_assets(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    CONSTRAINT profiles_display_name_nonempty CHECK (length(btrim(display_name)) > 0)
);
CREATE INDEX user_profiles_avatar_idx ON public.user_profiles (avatar_media_id) WHERE avatar_media_id IS NOT NULL;
CREATE INDEX user_profiles_cover_idx ON public.user_profiles (cover_media_id) WHERE cover_media_id IS NOT NULL;

-- RELATIONSHIPS / PRIVACY ------------------------------------------------------
-- Always store LEAST(A,B), GREATEST(A,B), not two directional friend rows.
CREATE TABLE public.friendships (
    user_low_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    user_high_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    requested_by_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    responded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (user_low_id, user_high_id),
    CONSTRAINT friendships_ordered_pair CHECK (user_low_id < user_high_id),
    CONSTRAINT friendships_requester_in_pair CHECK (requested_by_id IN (user_low_id, user_high_id)),
    CONSTRAINT friendships_status_valid CHECK (status IN ('PENDING','ACCEPTED','REJECTED','CANCELLED','REMOVED')),
    CONSTRAINT friendships_response_state CHECK ((status = 'PENDING') = (responded_at IS NULL))
);
CREATE INDEX friendships_low_status_idx ON public.friendships (user_low_id, status, user_high_id);
CREATE INDEX friendships_high_status_idx ON public.friendships (user_high_id, status, user_low_id);
CREATE INDEX friendships_requester_idx ON public.friendships (requested_by_id);

CREATE TABLE public.user_blocks (
    blocker_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    blocked_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (blocker_id, blocked_id),
    CONSTRAINT user_blocks_not_self CHECK (blocker_id <> blocked_id)
);
CREATE INDEX user_blocks_reverse_idx ON public.user_blocks (blocked_id, blocker_id);

-- Chosen meaning: restricted user can see only restrictor's PUBLIC posts.
CREATE TABLE public.user_restrictions (
    restrictor_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    restricted_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (restrictor_id, restricted_id),
    CONSTRAINT user_restrictions_not_self CHECK (restrictor_id <> restricted_id)
);
CREATE INDEX user_restrictions_reverse_idx ON public.user_restrictions (restricted_id, restrictor_id);

-- POSTS / FEED ----------------------------------------------------------------
CREATE TABLE public.posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'ORIGINAL',
    content TEXT,
    visibility TEXT NOT NULL DEFAULT 'PUBLIC',
    shared_post_id UUID REFERENCES public.posts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT posts_kind_valid CHECK (kind IN ('ORIGINAL','SHARE')),
    CONSTRAINT posts_visibility_valid CHECK (visibility IN ('PUBLIC','FRIENDS','PRIVATE')),
    CONSTRAINT posts_content_valid CHECK (content IS NULL OR (length(btrim(content)) > 0 AND length(content) <= 10000)),
    CONSTRAINT posts_not_self_share CHECK (shared_post_id IS DISTINCT FROM id),
    CONSTRAINT posts_original_has_no_source CHECK (kind <> 'ORIGINAL' OR shared_post_id IS NULL)
    -- SHARE with NULL source is retained only when the original is physically deleted.
    -- A trigger prevents creating a SHARE without a live ORIGINAL source.
);
CREATE INDEX posts_author_feed_idx ON public.posts (author_id, created_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX posts_feed_idx ON public.posts (created_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX posts_shared_source_idx ON public.posts (shared_post_id) WHERE shared_post_id IS NOT NULL;

CREATE TABLE public.post_attachments (
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    media_id UUID NOT NULL REFERENCES public.media_assets(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL,
    alt_text VARCHAR(500),
    PRIMARY KEY (post_id, position),
    CONSTRAINT post_attachments_media_uq UNIQUE (post_id, media_id),
    CONSTRAINT post_attachments_position CHECK (position >= 0)
);
CREATE INDEX post_attachments_media_idx ON public.post_attachments (media_id);

CREATE TABLE public.post_reactions (
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    reaction_type TEXT NOT NULL DEFAULT 'LIKE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (post_id, user_id),
    CONSTRAINT post_reactions_type CHECK (reaction_type = 'LIKE')
);
CREATE INDEX post_reactions_user_idx ON public.post_reactions (user_id);
CREATE INDEX post_reactions_list_idx ON public.post_reactions (post_id, created_at DESC, user_id DESC);

CREATE TABLE public.hidden_posts (
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (user_id, post_id)
);
CREATE INDEX hidden_posts_post_idx ON public.hidden_posts (post_id);

-- COMMENTS -------------------------------------------------------------------
CREATE TABLE public.comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    parent_comment_id UUID,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT comments_content_valid CHECK (length(btrim(content)) BETWEEN 1 AND 3000),
    CONSTRAINT comments_not_self_parent CHECK (parent_comment_id IS DISTINCT FROM id),
    CONSTRAINT comments_post_id_id_uq UNIQUE (post_id, id),
    CONSTRAINT comments_same_post_parent_fk FOREIGN KEY (post_id, parent_comment_id)
        REFERENCES public.comments(post_id, id) ON DELETE CASCADE
);
CREATE INDEX comments_thread_idx ON public.comments (post_id, parent_comment_id, created_at, id);
CREATE INDEX comments_author_idx ON public.comments (author_id);
CREATE INDEX comments_parent_idx ON public.comments (post_id, parent_comment_id) WHERE parent_comment_id IS NOT NULL;

CREATE TABLE public.comment_likes (
    comment_id UUID NOT NULL REFERENCES public.comments(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (comment_id, user_id)
);
CREATE INDEX comment_likes_user_idx ON public.comment_likes (user_id);

-- DIRECT CHAT ----------------------------------------------------------------
CREATE TABLE public.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_low_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    user_high_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    last_message_seq BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    CONSTRAINT conversations_pair_uq UNIQUE (user_low_id, user_high_id),
    CONSTRAINT conversations_ordered_pair CHECK (user_low_id < user_high_id),
    CONSTRAINT conversations_seq_nonnegative CHECK (last_message_seq >= 0)
);
CREATE INDEX conversations_high_user_idx ON public.conversations (user_high_id);

CREATE TABLE public.conversation_members (
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    last_read_seq BIGINT,
    last_read_at TIMESTAMPTZ,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (conversation_id, user_id),
    CONSTRAINT conversation_members_read_seq CHECK (last_read_seq IS NULL OR last_read_seq > 0)
);
CREATE INDEX conversation_members_user_idx ON public.conversation_members (user_id, conversation_id);

CREATE TABLE public.messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    sender_id UUID NOT NULL,
    seq BIGINT NOT NULL,
    client_message_id UUID NOT NULL,
    body TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT messages_seq_positive CHECK (seq > 0),
    CONSTRAINT messages_body_valid CHECK (body IS NULL OR (length(btrim(body)) BETWEEN 1 AND 5000)),
    CONSTRAINT messages_conversation_seq_uq UNIQUE (conversation_id, seq),
    CONSTRAINT messages_client_id_uq UNIQUE (conversation_id, sender_id, client_message_id),
    CONSTRAINT messages_sender_member_fk FOREIGN KEY (conversation_id, sender_id)
        REFERENCES public.conversation_members(conversation_id, user_id) ON DELETE CASCADE
);
CREATE INDEX messages_sender_member_idx ON public.messages (conversation_id, sender_id);

-- The read marker must reference an existing sequence in this conversation.
ALTER TABLE public.conversation_members ADD CONSTRAINT conversation_members_read_message_fk
    FOREIGN KEY (conversation_id, last_read_seq)
    REFERENCES public.messages(conversation_id, seq) ON DELETE SET NULL (last_read_seq);

CREATE TABLE public.message_attachments (
    message_id UUID NOT NULL REFERENCES public.messages(id) ON DELETE CASCADE,
    media_id UUID NOT NULL REFERENCES public.media_assets(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL,
    PRIMARY KEY (message_id, position),
    CONSTRAINT message_attachments_media_uq UNIQUE (message_id, media_id),
    CONSTRAINT message_attachments_position CHECK (position >= 0)
);
CREATE INDEX message_attachments_media_idx ON public.message_attachments (media_id);

-- TIMESTAMPS / STRUCTURAL INVARIANTS ------------------------------------------
CREATE FUNCTION public.touch_updated_at() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;
DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['users','user_profiles','media_assets','friendships',
                                     'posts','post_reactions','comments','conversations','messages']
    LOOP
        EXECUTE format('CREATE TRIGGER touch_updated_at BEFORE UPDATE ON public.%I '
                       'FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at()', table_name);
    END LOOP;
END;
$$;

CREATE FUNCTION public.guard_post_source() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.author_id IS DISTINCT FROM OLD.author_id
           OR NEW.kind IS DISTINCT FROM OLD.kind THEN
            RAISE EXCEPTION 'Post id, author and kind are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.shared_post_id IS DISTINCT FROM OLD.shared_post_id THEN
            -- Allow only the FK's SET NULL when the source was physically deleted.
            IF NOT (NEW.shared_post_id IS NULL AND OLD.shared_post_id IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM public.posts WHERE id = OLD.shared_post_id)) THEN
                RAISE EXCEPTION 'Share source is immutable' USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF NEW.kind = 'SHARE' THEN
        IF NEW.shared_post_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.posts p WHERE p.id = NEW.shared_post_id
            AND p.kind = 'ORIGINAL' AND p.deleted_at IS NULL
        ) THEN
            RAISE EXCEPTION 'Share requires a live original post' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_post_source BEFORE INSERT OR UPDATE ON public.posts
    FOR EACH ROW EXECUTE FUNCTION public.guard_post_source();

-- Support one reply level. MVP sends parent_comment_id = NULL.
CREATE FUNCTION public.guard_comment_parent() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.post_id IS DISTINCT FROM OLD.post_id
           OR NEW.author_id IS DISTINCT FROM OLD.author_id
           OR NEW.parent_comment_id IS DISTINCT FROM OLD.parent_comment_id THEN
            RAISE EXCEPTION 'Comment identity, post, author and parent are immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.parent_comment_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.comments c WHERE c.id = NEW.parent_comment_id
        AND (c.parent_comment_id IS NOT NULL OR c.deleted_at IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'Reply requires a live root comment' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_comment_parent BEFORE INSERT OR UPDATE ON public.comments
    FOR EACH ROW EXECUTE FUNCTION public.guard_comment_parent();

CREATE FUNCTION public.guard_conversation_pair() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_low_id IS DISTINCT FROM OLD.user_low_id
       OR NEW.user_high_id IS DISTINCT FROM OLD.user_high_id THEN
        RAISE EXCEPTION 'Direct conversation identity and pair are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_conversation_pair BEFORE UPDATE ON public.conversations
    FOR EACH ROW EXECUTE FUNCTION public.guard_conversation_pair();

CREATE FUNCTION public.add_direct_members() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.conversation_members (conversation_id, user_id)
    VALUES (NEW.id, NEW.user_low_id), (NEW.id, NEW.user_high_id);
    RETURN NEW;
END;
$$;
CREATE TRIGGER add_direct_members AFTER INSERT ON public.conversations
    FOR EACH ROW EXECUTE FUNCTION public.add_direct_members();

CREATE FUNCTION public.guard_direct_member() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
                            OR NEW.user_id IS DISTINCT FROM OLD.user_id) THEN
        RAISE EXCEPTION 'Conversation membership identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = NEW.conversation_id
                   AND NEW.user_id IN (c.user_low_id, c.user_high_id)) THEN
        RAISE EXCEPTION 'Member must belong to the direct conversation pair' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_direct_member BEFORE INSERT OR UPDATE OF conversation_id, user_id
    ON public.conversation_members FOR EACH ROW EXECUTE FUNCTION public.guard_direct_member();

-- Atomic UPDATE locks the conversation until commit and assigns an ordered per-thread sequence.
CREATE FUNCTION public.assign_message_seq() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE public.conversations SET last_message_seq = last_message_seq + 1
    WHERE id = NEW.conversation_id RETURNING last_message_seq INTO NEW.seq;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Conversation does not exist' USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER assign_message_seq BEFORE INSERT ON public.messages
    FOR EACH ROW EXECUTE FUNCTION public.assign_message_seq();

CREATE FUNCTION public.guard_message_identity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
       OR NEW.sender_id IS DISTINCT FROM OLD.sender_id OR NEW.seq IS DISTINCT FROM OLD.seq
       OR NEW.client_message_id IS DISTINCT FROM OLD.client_message_id THEN
        RAISE EXCEPTION 'Message identity and sequence are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_message_identity BEFORE UPDATE ON public.messages
    FOR EACH ROW EXECUTE FUNCTION public.guard_message_identity();

-- READ POLICY HELPERS ---------------------------------------------------------
-- Authenticated-user PUBLIC policy; invoker permissions; not RLS.
-- The backend supplies viewer_id from the verified JWT, never from a client-selected id.
CREATE FUNCTION public.can_read_author_post(viewer_id UUID, post_author_id UUID, post_visibility TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.users author
        WHERE author.id = post_author_id AND author.status = 'ACTIVE' AND author.deleted_at IS NULL
        AND EXISTS (SELECT 1 FROM public.users viewer
                    WHERE viewer.id = viewer_id AND viewer.status = 'ACTIVE' AND viewer.deleted_at IS NULL)
        AND NOT EXISTS (SELECT 1 FROM public.user_blocks b
                         WHERE (b.blocker_id = viewer_id AND b.blocked_id = post_author_id)
                            OR (b.blocker_id = post_author_id AND b.blocked_id = viewer_id))
        AND (
            viewer_id = post_author_id OR post_visibility = 'PUBLIC'
            OR (post_visibility = 'FRIENDS'
                AND EXISTS (SELECT 1 FROM public.friendships f
                            WHERE f.user_low_id = LEAST(viewer_id, post_author_id)
                              AND f.user_high_id = GREATEST(viewer_id, post_author_id)
                              AND f.status = 'ACCEPTED')
                AND NOT EXISTS (SELECT 1 FROM public.user_restrictions r
                                WHERE r.restrictor_id = post_author_id AND r.restricted_id = viewer_id))
        )
    );
$$;

CREATE FUNCTION public.can_view_post(target_post_id UUID, viewer_id UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.posts p
        WHERE p.id = target_post_id AND p.deleted_at IS NULL
          AND public.can_read_author_post(viewer_id, p.author_id, p.visibility)
          AND (p.kind = 'ORIGINAL' OR EXISTS (
              SELECT 1 FROM public.posts original
              WHERE original.id = p.shared_post_id AND original.kind = 'ORIGINAL'
                AND original.deleted_at IS NULL
                AND public.can_read_author_post(viewer_id, original.author_id, original.visibility)
          ))
    );
$$;

COMMENT ON TABLE public.auth_sessions IS 'JWT sid resolves to this session; check revocation, expiry and user state on every authenticated request.';
COMMENT ON TABLE public.friendships IS 'One current relationship per unordered pair, not a history of friend-request attempts.';
COMMENT ON TABLE public.posts IS 'SHARE content is the caption; shared_post_id references the live ORIGINAL. Authorize both source and share.';
COMMENT ON TABLE public.media_assets IS 'Object storage metadata; do not store image bytes or persist expiring signed URLs.';
COMMENT ON COLUMN public.users.created_at IS 'Profile joined date is derived from this field.';
COMMENT ON COLUMN public.messages.seq IS 'Assigned by trigger, strictly ordered within one conversation; gaps are allowed.';
COMMENT ON COLUMN public.conversation_members.last_read_seq IS 'NULL means no message read; only advance this marker in backend updates.';
COMMIT;
