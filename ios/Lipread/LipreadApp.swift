import SwiftUI

@main
struct LipreadApp: App {
    @StateObject private var session = SessionStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(session)
                .task { await session.bootstrap() }
        }
    }
}

/// Shows the sign-in screen until authenticated, then the main tabs.
struct RootView: View {
    @EnvironmentObject var session: SessionStore

    var body: some View {
        Group {
            if session.isAuthenticated {
                ContentView()
            } else {
                AuthView()
            }
        }
        .animation(.default, value: session.isAuthenticated)
    }
}
