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
