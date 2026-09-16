import SwiftUI

struct ContentView: View {
    @EnvironmentObject var session: SessionStore
    // One camera shared by Speak + Teach — two capture sessions on the same
    // device would conflict.
    @StateObject private var camera = CameraController()

    var body: some View {
        TabView {
            SpeakView()
                .tabItem { Label("Speak", systemImage: "mouth") }
            ComingSoon(title: "Voices")
                .tabItem { Label("Voices", systemImage: "mic") }
            TeachView()
                .tabItem { Label("Teach", systemImage: "graduationcap") }
            AccountView()
                .tabItem { Label("Account", systemImage: "person.crop.circle") }
        }
        .environmentObject(camera)
        .task { await camera.configure() }
    }
}

struct ComingSoon: View {
    let title: String
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "hammer").font(.largeTitle).foregroundStyle(.secondary)
            Text("\(title) — coming next").foregroundStyle(.secondary)
        }
    }
}

struct AccountView: View {
    @EnvironmentObject var session: SessionStore
    var body: some View {
        VStack(spacing: 16) {
            if let email = session.email { Text(email).font(.headline) }
            Button("Log out", role: .destructive) { Task { await session.signOut() } }
                .buttonStyle(.bordered)
        }
        .padding()
    }
}
