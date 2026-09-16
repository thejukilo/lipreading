import AVFoundation
import CoreImage
import UIKit

/// Front-camera capture. While `isRecording`, frames are throttled to ~25 fps
/// (the model's training rate), delivered upright, downscaled and JPEG-encoded.
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
    private nonisolated(unsafe) var lastKept = CMTime.negativeInfinity
    private let maxSide: CGFloat = 480
    private let targetInterval = 0.039   // ~25 fps to match the model

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
        // Deliver upright (portrait) frames — the sensor is landscape by default,
        // which would hand the mouth-crop a sideways face.
        if let conn = output.connection(with: .video) {
            if #available(iOS 17.0, *) {
                if conn.isVideoRotationAngleSupported(90) { conn.videoRotationAngle = 90 }
            } else if conn.isVideoOrientationSupported {
                conn.videoOrientation = .portrait
            }
        }
        session.commitConfiguration()
        session.startRunning()
    }

    func startRecording() {
        queue.async { [weak self] in
            self?.buffer = []
            self?.lastKept = .negativeInfinity
            self?.recording = true
        }
    }

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
        guard recording, let px = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        // Throttle to ~25 fps (the sensor delivers ~30) to match the model.
        let ts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if lastKept != .negativeInfinity,
           CMTimeGetSeconds(CMTimeSubtract(ts, lastKept)) < targetInterval { return }
        lastKept = ts

        var image = CIImage(cvPixelBuffer: px)
        let extent = image.extent
        let scale = min(1, maxSide / max(extent.width, extent.height))
        if scale < 1 { image = image.transformed(by: .init(scaleX: scale, y: scale)) }
        if let jpeg = ciContext.jpegRepresentation(
            of: image, colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.6]) {
            buffer.append(jpeg)
        }
    }
}
