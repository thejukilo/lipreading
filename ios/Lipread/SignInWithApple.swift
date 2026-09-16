import AuthenticationServices
import CryptoKit
import Foundation
import SwiftUI

/// Helpers for Sign in with Apple → Supabase (needs a nonce: raw nonce sent to
/// Supabase, its SHA-256 sent to Apple).
enum AppleAuth {
    static func randomNonce(length: Int = 32) -> String {
        let chars = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-._")
        var result = ""
        var remaining = length
        while remaining > 0 {
            var random: UInt8 = 0
            _ = SecRandomCopyBytes(kSecRandomDefault, 1, &random)
            if Int(random) < chars.count { result.append(chars[Int(random)]); remaining -= 1 }
        }
        return result
    }

    static func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// A Sign in with Apple button that drives the Supabase sign-in.
struct AppleSignInButton: View {
    @EnvironmentObject var session: SessionStore
    @State private var currentNonce = ""

    var body: some View {
        SignInWithAppleButton(.signIn) { request in
            let nonce = AppleAuth.randomNonce()
            currentNonce = nonce
            request.requestedScopes = [.fullName, .email]
            request.nonce = AppleAuth.sha256(nonce)
        } onCompletion: { result in
            switch result {
            case .success(let auth):
                guard
                    let cred = auth.credential as? ASAuthorizationAppleIDCredential,
                    let tokenData = cred.identityToken,
                    let idToken = String(data: tokenData, encoding: .utf8)
                else { return }
                let nonce = currentNonce
                Task { await session.signInWithApple(idToken: idToken, nonce: nonce) }
            case .failure(let error):
                session.authError = error.localizedDescription
            }
        }
        .signInWithAppleButtonStyle(.white)
        .frame(height: 50)
    }
}
