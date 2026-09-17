import AVFoundation
import Foundation

/// Records a short mono WAV clip (LinearPCM) to use as a voice-cloning
/// reference. The backend accepts WAV only, so we record LinearPCM directly.
@MainActor
final class VoiceRecorder: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var elapsed: TimeInterval = 0
    @Published var permissionDenied = false

    private var recorder: AVAudioRecorder?
    private var url: URL?
    private var timer: Timer?

    /// Ask for mic access up front (call from .task/.onAppear).
    func requestPermission() {
        AVAudioApplication.requestRecordPermission { granted in
            Task { @MainActor in self.permissionDenied = !granted }
        }
    }

    func start() {
        guard !isRecording else { return }
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)
        } catch {
            print("audio session failed: \(error)")
            return
        }

        let dest = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 16_000,        // plenty for speaker reference
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        do {
            let r = try AVAudioRecorder(url: dest, settings: settings)
            r.record()
            recorder = r
            url = dest
            isRecording = true
            elapsed = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                guard let self, let r = self.recorder else { return }
                Task { @MainActor in self.elapsed = r.currentTime }
            }
        } catch {
            print("recorder init failed: \(error)")
        }
    }

    /// Stop and return the recorded WAV bytes (nil if too short / failed).
    func stop() -> Data? {
        timer?.invalidate(); timer = nil
        guard let r = recorder else { return nil }
        r.stop()
        isRecording = false
        recorder = nil
        defer { if let u = url { try? FileManager.default.removeItem(at: u) } }
        guard let u = url, let data = try? Data(contentsOf: u) else { return nil }
        return data
    }

    func cancel() {
        timer?.invalidate(); timer = nil
        recorder?.stop()
        recorder = nil
        isRecording = false
        if let u = url { try? FileManager.default.removeItem(at: u) }
        url = nil
    }
}
