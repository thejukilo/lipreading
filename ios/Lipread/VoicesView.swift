import SwiftUI

/// Manage voice-cloning speakers: record a reference clip → name it → clone,
/// pick the active voice, preview, and delete. Cloning is zero-shot (the clip
/// is stored and applied at speak time), so it completes in seconds.
struct VoicesView: View {
    @EnvironmentObject var session: SessionStore
    @StateObject private var rec = VoiceRecorder()

    @State private var voices: [APIClient.Voice] = []
    @State private var name = ""
    @State private var phase: Phase = .idle
    @State private var status = "Record ~10s of your voice, name it, and clone."
    @State private var loadError: String?
    @State private var pendingWav: Data?
    @FocusState private var editing: Bool

    enum Phase { case idle, recording, cloning }

    private var api: APIClient { APIClient(session: session) }

    /// A sentence with varied sounds — good reference material to read aloud.
    private let promptText =
        "The quick brown fox jumps over the lazy dog while I count one, two, three, four, five."

    var body: some View {
        NavigationStack {
            Form {
                recordSection
                voicesSection
            }
            .navigationTitle("Voices")
        }
        .task {
            rec.requestPermission()
            await load()
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer(); Button("Done") { editing = false }
            }
        }
    }

    // MARK: - Record / clone

    private var recordSection: some View {
        Section("Add a voice") {
            TextField("Voice name (e.g. My voice)", text: $name)
                .focused($editing)

            Text("Say anything in your normal voice for about 10 seconds — talk about your day, or read the suggestion below.")
                .font(.caption).foregroundStyle(.secondary)
            Text("Suggestion: “\(promptText)”")
                .font(.callout).italic().foregroundStyle(.secondary)

            if rec.permissionDenied {
                Text("Microphone access is off. Enable it in Settings › Lipread › Microphone.")
                    .font(.footnote).foregroundStyle(.red)
            }

            switch phase {
            case .cloning:
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Cloning “\(name)”…").font(.footnote)
                }
            case .recording:
                Button(role: .destructive) { stopAndClone() } label: {
                    Label(String(format: "Recording… %.0fs — tap to finish", rec.elapsed),
                          systemImage: "stop.circle.fill")
                }
            case .idle:
                Button {
                    startRecording()
                } label: {
                    Label("Record & clone", systemImage: "mic.circle.fill")
                }
                .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || rec.permissionDenied)
            }

            Text(status).font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func startRecording() {
        editing = false
        rec.start()
        phase = .recording
        status = "Recording — read the sentence, then tap to finish."
    }

    private func stopAndClone() {
        let wav = rec.stop()
        guard let wav, rec.elapsed >= 1.5 || wav.count > 40_000 else {
            phase = .idle
            status = "That was too short — record a few seconds of speech."
            return
        }
        pendingWav = wav
        Task { await clone(wav: wav) }
    }

    private func clone(wav: Data) async {
        phase = .cloning
        let voiceName = name.trimmingCharacters(in: .whitespaces)
        do {
            let v = try await api.createVoice(name: voiceName, wav: wav)
            status = "Cloned “\(v.name)” ✓ — it's now your speaker."
            name = ""
            pendingWav = nil
            await load()
        } catch {
            status = "Clone failed: \(error.localizedDescription)"
        }
        phase = .idle
    }

    // MARK: - List / select / delete

    private var voicesSection: some View {
        Section("Your voices") {
            if let err = loadError {
                Text(err).font(.footnote).foregroundStyle(.red)
                Button("Retry") { Task { await load() } }
            } else if voices.isEmpty {
                Text("No voices yet. Record one above — the app uses the base voice until then.")
                    .font(.footnote).foregroundStyle(.secondary)
            } else {
                ForEach(voices) { v in
                    HStack {
                        Image(systemName: v.is_default ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(v.is_default ? .green : .secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(v.name)
                            Text(v.is_default ? "Active speaker" : "Tap to use")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button { Task { await preview(v) } } label: {
                            Image(systemName: "play.circle")
                        }.buttonStyle(.borderless)
                    }
                    .contentShape(Rectangle())
                    .onTapGesture { Task { await select(v) } }
                }
                .onDelete { idx in Task { await deleteAt(idx) } }
            }
        }
    }

    private func load() async {
        loadError = nil
        do { voices = try await api.listVoices() }
        catch { loadError = "Couldn't load voices: \(error.localizedDescription)" }
    }

    private func select(_ v: APIClient.Voice) async {
        guard !v.is_default else { return }
        do {
            _ = try await api.setDefaultVoice(id: v.id)
            status = "“\(v.name)” is now your speaker."
            await load()
        } catch { status = error.localizedDescription }
    }

    private func preview(_ v: APIClient.Voice) async {
        do { AudioPlayer.shared.play(data: try await api.voiceReference(id: v.id)) }
        catch { status = "Couldn't play preview: \(error.localizedDescription)" }
    }

    private func deleteAt(_ idx: IndexSet) async {
        for i in idx {
            let v = voices[i]
            do { try await api.deleteVoice(id: v.id) }
            catch { status = "Delete failed: \(error.localizedDescription)" }
        }
        await load()
    }
}
