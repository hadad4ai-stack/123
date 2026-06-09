BEGIN;

-- Create or replace function to change user role flags
CREATE OR REPLACE FUNCTION public.set_user_role(
    _target_uid uuid,
    _is_admin boolean DEFAULT NULL,
    _is_structural_allowed boolean DEFAULT NULL
)
RETURNS void
SECURITY DEFINER
LANGUAGE plpgsql
AS $$
DECLARE
    caller_is_admin boolean;
BEGIN
    -- Verify caller has elevated privileges
    SELECT (is_admin OR is_structural_allowed)
    INTO caller_is_admin
    FROM public.ai_profiles
    WHERE user_id = auth.uid();

    IF NOT caller_is_admin THEN
        RAISE EXCEPTION 'Insufficient privileges to change roles';
    END IF;

    -- Update role flags for the target user
    UPDATE public.ai_profiles
    SET
        is_admin = COALESCE(_is_admin, is_admin),
        is_structural_allowed = COALESCE(_is_structural_allowed, is_structural_allowed)
    WHERE user_id = _target_uid;
END;
$$;

-- Grant execution to authenticated users (internal logic restricts to admins)
GRANT EXECUTE ON FUNCTION public.set_user_role(uuid, boolean, boolean) TO authenticated;

COMMIT;
