BEGIN;

-- Add is_structural_allowed column if it does not exist
DO $$
BEGIN
  IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'ai_profiles'
        AND column_name = 'is_structural_allowed'
  ) THEN
    ALTER TABLE public.ai_profiles
      ADD COLUMN is_structural_allowed BOOLEAN DEFAULT FALSE;
  END IF;
END$$;

-- Create helper function for bypass (admin OR structural)
CREATE OR REPLACE FUNCTION public._structural_bypass()
RETURNS BOOLEAN
STABLE
LANGUAGE sql AS $$
  SELECT EXISTS (
      SELECT 1 FROM public.ai_profiles p
      WHERE p.user_id = auth.uid()
        AND (p.is_admin IS TRUE OR p.is_structural_allowed IS TRUE)
  );
$$;

COMMIT;
