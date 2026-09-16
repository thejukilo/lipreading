import AVFoundation
import CoreImage
import UIKit

/// Front-camera capture. While `isRecording`, each frame is downscaled and
/// JPEG-encoded into `frames` (mirrors the web client's push-to-talk upload).
@MainActor
final class CameraController: NSObject, ObservableObject {
    @Published var authorized = false
    let session = AVCaptureSession()

    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "camera.frames")
    // Touched only on `queue`, so we manage the synchronization ourselves.
    private nonisolated(unsafe) let ciContext = CIContext()
    private nonisolated(unsafe) var recording = false
    private nonisolated(unsafe) var buffer: [Data] = []
    private let maxSide: CGFloat = 480

    func configure() async {
        let ok = await Self.requestCameraAccess()
        authorized = ok
        guard ok else { return }
        queue.async { [weak self] in self?.setup() }
    }

    private func setup() {
        session.beginConfiguration()
        session.sessionPreset = .vga640x480
        if let cam = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
           let input = try? AVCaptureDeviceInput(device: cam),
           session.canAddInput(input) {
            session.addInput(input)
        }
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }
        session.commitConfiguration()
        session.startRunning()
    }

    func startRecording() {
        queue.async { [weak self] in self?.buffer = []; self?.recording = true }
    }

    /// Stop and return the captured JPEG frames.
    func stopRecording() async -> [Data] {
        await withCheckedContinuation { cont in
            queue.async { [weak self] in
                self?.recording = false
                cont.resume(returning: self?.buffer ?? [])
            }
        }
    }

    private static func requestCameraAccess() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: .video)
        default: return false
        }
    }
}

extension CameraController: AVCaptureVideoDataOutputSampleBufferDelegate {
    nonisolated func captureOutput(_ output: AVCaptureOutput,
                                   didOutput sampleBuffer: CMSampleBuffer,
                                   from connection: AVCaptureConnection) {
        // Runs on `queue`; `recording`/`buffer` are only touched here + in the
        // queue-hopping methods above, so this stays serialized.
        guard recording, let px = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        var image = CIImage(cvPixelBuffer: px)
        let extent = image.extent
        let scale = min(1, maxSide / max(extent.width, extent.height))
        if scale < 1 {
            image = image.transformed(by: .init(scaleX: scale, y: scale))
        }
        if let jpeg = ciContext.jpegRepresentation(of: image,
                                                   colorSpace: CGColorSpaceCreateDeviceRGB(),
                                                   options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.6]) {
            buffer.append(jpeg)
        }
    }
}
