import SwiftUI

struct AuthView: View {
    @EnvironmentObject var session: SessionStore
    @State private var email = ""
    @State private var password = ""
    @State private var isSignUp = false
    @State private var busy = false

    var body: some View {
        VStack(spacing: 16) {
            Spacer()
            Text("Lipreading").font(.largeTitle.bold())
            Text(isSignUp ? "Create an account." : "Speak with your eyes.")
                .foregroundStyle(.secondary)

            TextField("Email", text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding().background(.quaternary).clipShape(.rect(cornerRadius: 12))

            SecureField("Password", text: $password)
                .textContentType(isSignUp ? .newPassword : .password)
                .padding().background(.quaternary).clipShape(.rect(cornerRadius: 12))

            if let err = session.authError {
                Text(err).font(.footnote).foregroundStyle(.red)
            }

            Button {
                Task {
                    busy = true
                    if isSignUp { await session.signUp(email: email, password: password) }
                    else { await session.signIn(email: email, password: password) }
                    busy = false
                }
            } label: {
                Text(isSignUp ? "Create account" : "Sign in")
                    .frame(maxWidth: .infinity).padding()
            }
            .buttonStyle(.borderedProminent)
            .disabled(busy || email.isEmpty || password.isEmpty)

            Button(isSignUp ? "Have an account? Sign in" : "New here? Create an account") {
                isSignUp.toggle(); session.authError = nil
            }
            .font(.footnote)

            HStack { Rectangle().frame(height: 1).opacity(0.2); Text("or").foregroundStyle(.secondary); Rectangle().frame(height: 1).opacity(0.2) }

            AppleSignInButton()

            Spacer()
        }
        .padding(24)
    }
}
