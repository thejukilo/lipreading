import Foundation

/// App configuration. Fill these in (or better, load from xcconfig / build
/// settings). The Supabase URL + anon key are public client values — safe to
/// ship in the app. The API base URL is your backend: an ngrok tunnel to your
/// PC now, the RunPod pod URL later.
enum Config {
    static let supabaseURL = URL(string: "https://mbmajkrmvtlszirgtgre.supabase.co")!

    /// Supabase → Project Settings → API → Project API keys → `anon` `public`.
    static let supabaseAnonKey = "PASTE_YOUR_SUPABASE_ANON_KEY"

    /// Your backend base URL, no trailing slash.
    /// Dev:  your ngrok https URL (e.g. https://abcd-1234.ngrok-free.app)
    /// Prod: https://<pod>-8000.proxy.runpod.net
    static let apiBaseURL = URL(string: "https://YOUR-NGROK-OR-RUNPOD-URL")!
}
