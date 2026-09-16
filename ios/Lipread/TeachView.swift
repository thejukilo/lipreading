import SwiftUI

struct TeachView: View {
    @EnvironmentObject var session: SessionStore
    @StateObject private var camera = CameraController()

    @State private var target = ""                       // phrase to record now
    @State private var custom = ""                       // user-typed sentence
    @State private var queue: [String] = []              // prompted sentences
    @State private var practice: [APIClient.PracticePhrase] = []
    @State private var teachStatus: APIClient.TeachStatus?
    @State private var status = "Read sentences, or practice a correction, then train."
    @State private var isRecording = false
    @State private var busy = false
    @FocusState private var editing: Bool

    private var api: APIClient { APIClient(session: session) }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                ZStack {
                    CameraPreview(session: camera.session, mirrored: camera.position == .front)
                        .frame(width: 180, height: 180)
                        .clipShape(.rect(cornerRadius: 18))
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(.white.opacity(0.35), style: .init(lineWidth: 2, dash: [8]))
                        .frame(width: 150, height: 150)
                }
                .padding(.top, 8)

                Text(target.isEmpty ? "Pick a sentence or correction below." : target)
                    .font(.title3).multilineTextAlignment(.center)

                holdButton
                Text(status).font(.footnote).foregroundStyle(.secondary)

                // Your own sentence
                GroupBox("Train your own sentence") {
                    VStack(spacing: 8) {
                        TextField("Type a sentence to train", text: $custom, axis: .vertical)
                            .lineLimit(1...3)
                            .focused($editing)
                            .textFieldStyle(.roundedBorder)
                        Button("Use this sentence") {
                            let t = custom.trimmingCharacters(in: .whitespacesAndNewlines)
                            if !t.isEmpty { target = t; editing = false; status = "Hold to record: \(t)" }
                        }
                        .disabled(custom.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }.frame(maxWidth: .infinity)
                }

                // Prompted sentences
                GroupBox("Sentences to read") {
                    VStack(spacing: 8) {
                        if queue.isEmpty {
                            Button("Get sentences") { Task { await loadSentences() } }
                        } else {
                            Button {
                                target = queue.first ?? ""
                                status = "Hold to record: \(target)"
                            } label: {
                                Text("Now: “\(queue.first ?? "")” · \(queue.count) left")
                                    .font(.footnote).multilineTextAlignment(.center)
                            }
                            HStack {
                                Button("Skip") { advance() }
                                Button("New set") { Task { await loadSentences() } }
                            }
                        }
                    }.frame(maxWidth: .infinity)
                }

                // Corrections (added from Speak)
                if !practice.isEmpty {
                    GroupBox("Corrections to practice") {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(practice) { p in
                                HStack(alignment: .top) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(p.text)
                                        Text("\(p.reps) clip\(p.reps == 1 ? "" : "s")\(p.reps >= 5 ? " · ready ✓" : " · record a few more")")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Button("Record") {
                                        target = p.text
                                        status = "Hold to record: \(p.text)"
                                    }.buttonStyle(.bordered)
                                }
                            }
                        }
                    }
                }

                // Training
                GroupBox("Training") {
                    VStack(spacing: 8) {
                        if let s = teachStatus {
                            Text("\(s.samples_total) clips · \(s.new_since_train)/\(s.retrain_threshold) new toward auto-train")
                                .font(.footnote).foregroundStyle(.secondary)
                            if s.active_model_id != nil {
                                Text("Your private model is active ✅")
                                    .font(.footnote).foregroundStyle(.green)
                            }
                            if let job = s.latest_job {
                                Text("Last training: \(job.status)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Button { Task { await trainNow() } } label: {
                            Text("Train now").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled((teachStatus?.samples_total ?? 0) < 4)
                    }.frame(maxWidth: .infinity)
                }
            }
            .padding()
        }
        .task {
            await camera.configure()
            await refresh()
            if queue.isEmpty { await loadSentences() }
            // Poll while visible so training status updates live.
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                await refresh()
            }
        }
        .onDisappear { camera.stop() }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done") { editing = false }
            }
        }
    }

    private var holdButton: some View {
        Text(isRecording ? "Recording… release" : "Hold to record")
            .font(.headline).foregroundStyle(isRecording ? .black : .white)
            .frame(maxWidth: .infinity).padding(16)
            .background(target.isEmpty ? Color.gray : (isRecording ? Color.red : Color.green))
            .clipShape(.capsule)
            .opacity(busy ? 0.5 : 1)
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in if !isRecording && !busy && !target.isEmpty { startHold() } }
                .onEnded { _ in if isRecording { endHold() } })
    }

    private func startHold() {
        isRecording = true
        camera.startRecording()
        status = "recording…"
    }

    private func endHold() {
        isRecording = false
        let phrase = target
        Task {
            busy = true
            let frames = await camera.stopRecording()
            if frames.count < 8 { status = "too short — hold a bit longer"; busy = false; return }
            status = "saving… (\(frames.count) frames)"
            do {
                try await api.addSample(frames: frames, phrase: phrase)
                status = "saved ✓"
                if queue.first == phrase { advance() }
                await refresh()
            } catch {
                status = error.localizedDescription
            }
            busy = false
        }
    }

    private func advance() {
        if !queue.isEmpty { queue.removeFirst() }
        target = queue.first ?? ""
        if target.isEmpty { status = "Round done — get more sentences, or train." }
        else { status = "Read it aloud, holding the button." }
    }

    private func loadSentences() async {
        do {
            queue = try await api.teachSentences(n: 8)
            target = queue.first ?? ""
            status = "Read each one aloud, holding the button."
        } catch { status = error.localizedDescription }
    }

    private func trainNow() async {
        do {
            let j = try await api.teachTrain()
            status = "Training \(j.status)…"
            await refresh()
        } catch { status = error.localizedDescription }
    }

    private func refresh() async {
        teachStatus = try? await api.teachStatus()
        practice = (try? await api.teachPractice()) ?? []
    }
}
