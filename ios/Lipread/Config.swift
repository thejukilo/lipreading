import Foundation

/// App configuration. The Supabase URL + anon key are public client values —
/// safe to ship in the app. The API base URL is your backend: an ngrok tunnel
/// to your PC now, the RunPod pod URL later.
///
/// The API base URL can be overridden at runtime from Account → Server, so a
/// new ngrok URL doesn't need a rebuild (handy while testing).
enum Config {
    static let supabaseURL = URL(string: "https://mbmajkrmvtlszirgtgre.supabase.co")!

    /// Supabase → Project Settings → API → Project API keys → `anon` `public`.
    static let supabaseAnonKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1ibWFqa3JtdnRsc3ppcmd0Z3JlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc1NDU0NzQsImV4cCI6MjA5MzEyMTQ3NH0.Gsm-yfNSBdaCd1ub-Tz8Yv2kA_83G-durmIB9HSBksw"

    /// Compiled-in fallback backend URL, used until overridden in-app.
    /// Dev:  your ngrok https URL (e.g. https://abcd-1234.ngrok-free.app)
    /// Prod: https://<pod>-8000.proxy.runpod.net
    static let defaultAPIBaseURL = URL(string: "https://af61-31-165-106-25.ngrok-free.app")!

    private static let apiOverrideKey = "apiBaseURLOverride"

    /// Active backend base URL (no trailing slash). Uses the in-app override
    /// from Account → Server if set, otherwise the compiled default. Read fresh
    /// on every request, so changes take effect immediately — no rebuild.
    /// The override is stored already-normalized, so this never silently drops
    /// it back to the default.
    static var apiBaseURL: URL {
        if let s = UserDefaults.standard.string(forKey: apiOverrideKey), !s.isEmpty,
           let u = URL(string: s) {
            return u
        }
        return defaultAPIBaseURL
    }

    /// True when a custom server override is stored.
    static var hasAPIOverride: Bool {
        !(UserDefaults.standard.string(forKey: apiOverrideKey) ?? "").isEmpty
    }

    /// Save a user-entered base URL as the override. Returns the normalized URL
    /// on success, or nil if it can't be parsed (nothing is saved on nil, so the
    /// UI can show an error instead of silently reverting).
    @discardableResult
    static func setAPIOverride(_ raw: String) -> URL? {
        guard let u = normalizedURL(raw), u.host != nil else { return nil }
        UserDefaults.standard.set(u.absoluteString, forKey: apiOverrideKey)
        return u
    }

    /// Remove the override; apiBaseURL falls back to the compiled default.
    static func clearAPIOverride() {
        UserDefaults.standard.removeObject(forKey: apiOverrideKey)
    }

    /// Normalize typed input: trim, add https:// if missing, drop trailing "/".
    /// Uses `encodingInvalidCharacters` so a stray character percent-encodes
    /// instead of making the whole URL nil.
    static func normalizedURL(_ raw: String) -> URL? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        let lower = s.lowercased()
        if !lower.hasPrefix("http://") && !lower.hasPrefix("https://") {
            s = "https://" + s
        }
        while s.hasSuffix("/") { s.removeLast() }
        return URL(string: s, encodingInvalidCharacters: true)
    }
}
