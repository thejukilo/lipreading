import AVFoundation
import Foundation

/// Plays base64-encoded WAV audio returned by the backend.
final class AudioPlayer: NSObject {
    static let shared = AudioPlayer()
    private var player: AVAudioPlayer?

    func play(base64 wav: String) {
        guard let data = Data(base64Encoded: wav) else { return }
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
            player = try AVAudioPlayer(data: data)
            player?.play()
        } catch {
            // Non-fatal: the transcript still shows even if playback fails.
            print("audio playback failed: \(error)")
        }
    }
}
