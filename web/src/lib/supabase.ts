import { createClient, SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (_client) return _client;

  const url = "https://bhudzyrkyqwcqvqqaids.supabase.co" //process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJodWR6eXJreXF3Y3F2cXFhaWRzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE5NDI1NTksImV4cCI6MjA4NzUxODU1OX0.4R69jDIfQqBwRJl1ojyu3wuYyf8ozjdcZ-PZlipA1yk"// process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

  _client = createClient(url, key);
  return _client;
}

export const supabase =
  typeof window !== "undefined"
    ? getSupabase()
    : // During SSR/build, create a throwaway client that won't be used
      // because all data fetching happens in useEffect on the client.
      createClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL || "http://placeholder",
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder"
      );
