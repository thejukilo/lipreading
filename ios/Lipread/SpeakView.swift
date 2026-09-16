import SwiftUI

struct SpeakView: View {
    @EnvironmentObject var session: SessionStore
    @EnvironmentObject var camera: CameraController

    @State private var transcript = ""
    @State private var status = "Hold the button and mouth a sentence."
    @State private var isRecording = false
    @State private var busy = false
    @State private var cleanup = true
    @State private var speak = true
    @State private var lastFrames: [Data] = []
    @State private var showAddToTraining = false

    private var api: APIClient { APIClient(session: session) }

    var body: some View {
        VStack(spacing: 12) {
            ZStack {
                if camera.authorized {
                    CameraPreview(session: camera.session).clipShape(.rect(cornerRadius: 16))
                } else {
                    RoundedRectangle(cornerRadius: 16).fill(.black)
                        .overlay(Text("Camera access needed").foregroundStyle(.white))
                }
                RoundedRectangle(cornerRadius: 12).stroke(.white.opacity(0.3), style: .init(lineWidth: 2, dash: [8]))
                    .padding(40)
            }
            .frame(maxHeight: .infinity)

            Text(status).font(.footnote).foregroundStyle(.secondary)

            TextField("your words appear here — you can edit them", text: $transcript, axis: .vertical)
                .lineLimit(2...4)
                .padding().background(.quaternary).clipShape(.rect(cornerRadius: 12))

            if showAddToTraining {
                Button {
                    Task { await addToTraining() }
                } label: {
                    Label("Correct & add to training", systemImage: "pencil")
                        .frame(maxWidth: .infinity).padding(10)
                }
                .buttonStyle(.bordered)
            }

            // Push-to-talk.
            Text(isRecording ? "Recording… release to send" : "Hold to talk")
                .font(.headline).foregroundStyle(isRecording ? .black : .white)
                .frame(maxWidth: .infinity).padding(20)
                .background(isRecording ? Color.red : Color.green)
                .clipShape(.capsule)
                .opacity(busy ? 0.5 : 1)
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { _ in if !isRecording && !busy { startHold() } }
                        .onEnded { _ in if isRecording { endHold() } }
                )

            HStack(spacing: 20) {
                Toggle("Clean up", isOn: $cleanup).toggleStyle(.switch)
                Toggle("Speak", isOn: $speak).toggleStyle(.switch)
            }.font(.footnote)
        }
        .padding()
    }

    private func startHold() {
        isRecording = true
        showAddToTraining = false
        camera.startRecording()
        status = "recording…"
    }

    private func endHold() {
        isRecording = false
        Task {
            busy = true
            let frames = await camera.stopRecording()
            if frames.count < 8 { status = "too short — hold a bit longer"; busy = false; return }
            status = "thinking… (\(frames.count) frames)"
            do {
                let r = try await api.utter(frames: frames, speak: speak, cleanup: cleanup)
                transcript = r.text ?? ""
                status = r.message ?? "done — edit the text, then add to training"
                if let t = r.text, !t.isEmpty { lastFrames = frames; showAddToTraining = true }
                if let audio = r.audio { AudioPlayer.shared.play(base64: audio) }
            } catch {
                status = error.localizedDescription
            }
            busy = false
        }
    }

    private func addToTraining() async {
        let phrase = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !phrase.isEmpty, !lastFrames.isEmpty else { return }
        do {
            try await api.addSample(frames: lastFrames, phrase: phrase)
            status = "added ✓ — practice it a few more times on the Teach tab."
            showAddToTraining = false
        } catch {
            status = error.localizedDescription
        }
    }
}
