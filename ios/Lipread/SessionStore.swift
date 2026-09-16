import Foundation
import Supabase

/// Owns the Supabase client + auth state for the whole app.
@MainActor
final class SessionStore: ObservableObject {
    @Published var isAuthenticated = false
    @Published var email: String?
    @Published var authError: String?

    let client = SupabaseClient(supabaseURL: Config.supabaseURL,
                                supabaseKey: Config.supabaseAnonKey)

    /// Restore any persisted session and start listening for auth changes.
    func bootstrap() async {
        for await (event, session) in client.auth.authStateChanges {
            switch event {
            case .initialSession, .signedIn, .tokenRefreshed, .userUpdated:
                self.isAuthenticated = session != nil
                self.email = session?.user.email
            case .signedOut:
                self.isAuthenticated = false
                self.email = nil
            default:
                break
            }
        }
    }

    /// The current access token (JWT) to send to our backend as a Bearer token.
    func accessToken() async -> String? {
        try? await client.auth.session.accessToken
    }

    func signUp(email: String, password: String) async {
        authError = nil
        do {
            try await client.auth.signUp(email: email, password: password)
            // If email confirmation is ON, there's no session yet — surface that.
            if (try? await client.auth.session) == nil {
                authError = "Check your email to confirm your account, then sign in."
            }
        } catch {
            authError = error.localizedDescription
        }
    }

    func signIn(email: String, password: String) async {
        authError = nil
        do {
            try await client.auth.signIn(email: email, password: password)
        } catch {
            authError = error.localizedDescription
        }
    }

    /// Complete a Sign in with Apple flow using the Apple identity token.
    func signInWithApple(idToken: String, nonce: String) async {
        authError = nil
        do {
            try await client.auth.signInWithIdToken(
                credentials: .init(provider: .apple, idToken: idToken, nonce: nonce))
        } catch {
            authError = error.localizedDescription
        }
    }

    func signOut() async {
        try? await client.auth.signOut()
    }
}
