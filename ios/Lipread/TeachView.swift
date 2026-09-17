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
    @State private var lastSampleId: String?
    @State private var lastPhrase = ""
    @State private var reps = 3                          // takes per preset sentence
    @State private var repDone = 0                       // takes done for current one
    @FocusState private var editing: Bool

    private var api: APIClient { APIClient(session: session) }

    private var jobActive: Bool {
        let s = teachStatus?.latest_job?.status
        return s == "queued" || s == "running"
    }
    private var lastLogLine: String? {
        teachStatus?.latest_job?.log?
            .split(separator: "\n").last.map(String.init)
    }

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
                .overlay(alignment: .bottom) {
                    QualityBadge(quality: camera.quality)
                }
                .padding(.top, 8)

                Text(target.isEmpty ? "Pick a sentence or correction below." : target)
                    .font(.title3).multilineTextAlignment(.center)

                holdButton
                Text(status).font(.footnote).foregroundStyle(.secondary)

                if lastSampleId != nil {
                    Button(role: .destructive) {
                        Task { await discardLast() }
                    } label: {
                        Label("Discard that recording", systemImage: "trash")
                    }
                    .font(.footnote)
                }

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
                                Text("Now: “\(queue.first ?? "")” · take \(min(repDone + 1, reps))/\(reps) · \(queue.count) left")
                                    .font(.footnote).multilineTextAlignment(.center)
                            }
                            Stepper("Takes per sentence: \(reps)", value: $reps, in: 1...5)
                                .font(.footnote)
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
                                    Button(role: .destructive) {
                                        Task { await deletePractice(p) }
                                    } label: {
                                        Image(systemName: "trash")
                                    }.buttonStyle(.borderless)
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
                        }

                        if jobActive {
                            // Live progress while a run is in flight.
                            HStack(spacing: 8) {
                                ProgressView()
                                Text(teachStatus?.latest_job?.status == "queued"
                                     ? "Queued…" : "Training…")
                                    .font(.footnote)
                            }
                            if let line = lastLogLine {
                                Text(line)
                                    .font(.caption2.monospaced()).foregroundStyle(.secondary)
                                    .multilineTextAlignment(.center)
                            }
                        } else {
                            if let job = teachStatus?.latest_job {
                                Text(job.status == "failed"
                                     ? "Last training failed\(job.error.map { ": \($0)" } ?? "")"
                                     : "Last training: \(job.status)")
                                    .font(.caption)
                                    .foregroundStyle(job.status == "failed" ? .red : .secondary)
                            }
                            Text("Tip: personalization needs variety — record many different sentences (20+), not a few repeated.")
                                .font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        }

                        Button { Task { await trainNow() } } label: {
                            Text(jobActive ? "Training in progress…" : "Train now")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(jobActive || (teachStatus?.samples_total ?? 0) < 4)
                    }.frame(maxWidth: .infinity)
                }
            }
            .padding()
        }
        .task {
            await camera.configure()
            await refresh()
            if queue.isEmpty { await loadSentences() }
            // Poll while visible; faster while a training run is active.
            while !Task.isCancelled {
                let delay: UInt64 = jobActive ? 2_000_000_000 : 5_000_000_000
                try? await Task.sleep(nanoseconds: delay)
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
                let id = try await api.addSample(frames: frames, phrase: phrase)
                lastSampleId = id; lastPhrase = phrase
                if queue.first == phrase {
                    // Preset sentence: take several reps before moving on.
                    repDone += 1
                    if repDone >= reps {
                        advance()   // clears repDone, sets next sentence
                    } else {
                        status = "saved take \(repDone)/\(reps) of “\(phrase)” — hold to record again."
                    }
                } else {
                    status = "saved “\(phrase)” ✓ — wrong one? Discard it below."
                }
                await refresh()
            } catch {
                status = error.localizedDescription
            }
            busy = false
        }
    }

    private func discardLast() async {
        guard let id = lastSampleId else { return }
        do {
            try await api.deleteSample(id: id)
            status = "Discarded “\(lastPhrase)”."
            lastSampleId = nil
            await refresh()
        } catch {
            status = error.localizedDescription
        }
    }

    private func deletePractice(_ p: APIClient.PracticePhrase) async {
        do {
            try await api.deletePractice(id: p.id)
            if target == p.text { target = ""; status = "Removed “\(p.text)”." }
            await refresh()
        } catch {
            status = error.localizedDescription
        }
    }

    private func advance() {
        if !queue.isEmpty { queue.removeFirst() }
        repDone = 0
        target = queue.first ?? ""
        if target.isEmpty { status = "Round done — get more sentences, or train." }
        else { status = "Next: “\(target)” — record it \(reps)× (hold the button)." }
    }

    private func loadSentences() async {
        do {
            queue = try await api.teachSentences(n: 8)
            repDone = 0
            target = queue.first ?? ""
            status = "Read each one \(reps)× aloud, holding the button."
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
