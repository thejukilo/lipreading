import SwiftUI

struct ContentView: View {
    @EnvironmentObject var session: SessionStore

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
    @State private var info: APIClient.ModelInfo?
    @State private var busy = false
    @State private var msg = ""
    @State private var loadError: String?

    private var api: APIClient { APIClient(session: session) }

    var body: some View {
        NavigationStack {
            Form {
                Section("Account") {
                    if let email = session.email {
                        LabeledContent("Signed in", value: email)
                    }
                    Button("Log out", role: .destructive) {
                        Task { await session.signOut() }
                    }
                }

                Section("Recognition model") {
                    if let i = info {
                        Picker("Use", selection: Binding(
                            get: { i.active == "personal" },
                            set: { useP in Task { await select(useP) } })) {
                            Text("Base").tag(false)
                            Text("Personalized").tag(true)
                        }
                        .pickerStyle(.segmented)
                        .disabled(!i.has_personal || busy)

                        if i.active == "personal" {
                            LabeledContent("Last trained", value: i.trained_at.map(Self.dateStr) ?? "—")
                            LabeledContent("Trained on", value: "\(i.n_samples ?? 0) clips")
                        } else if i.has_personal {
                            Text("The general model shipped with the app. Switch to Personalized to use your trained model.")
                                .font(.footnote).foregroundStyle(.secondary)
                        } else {
                            Text("The general model shipped with the app. No personalized model yet — record varied sentences on Teach and train one.")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        LabeledContent("Your recordings",
                                       value: "\(i.total_clips) clips · \(i.distinct_phrases) sentences")
                    } else if let err = loadError {
                        Text(err).font(.footnote).foregroundStyle(.red)
                        Button("Retry") { Task { await load() } }
                    } else {
                        ProgressView()
                    }
                    if !msg.isEmpty {
                        Text(msg).font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Account")
        }
        .task { await load() }
    }

    private func load() async {
        loadError = nil
        do {
            info = try await api.modelInfo()
        } catch {
            loadError = "Couldn't load model info: \(error.localizedDescription). Is the backend running and updated (restart it after pulling)?"
        }
    }

    private func select(_ usePersonal: Bool) async {
        busy = true
        do {
            info = try await api.modelSelect(usePersonal: usePersonal)
            msg = usePersonal ? "Speak now uses your personalized model."
                              : "Speak now uses the base model."
        } catch {
            msg = error.localizedDescription
            info = try? await api.modelInfo()   // reflect the real state
        }
        busy = false
    }

    private static func dateStr(_ t: Double) -> String {
        let f = DateFormatter(); f.dateStyle = .medium; f.timeStyle = .short
        return f.string(from: Date(timeIntervalSince1970: t))
    }
}
