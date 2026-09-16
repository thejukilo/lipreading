import AVFoundation
import CoreImage
import UIKit
import Vision

/// Live camera-quality feedback (framing/lighting) for the preview.
struct QualityReport: Equatable {
    var ok = false
    var tip = "Checking camera…"
}

/// Front/back camera capture. While `isRecording`, frames are throttled to
/// ~25 fps (the model's rate), delivered upright, downscaled and JPEG-encoded.
/// The back camera lets you read *someone else's* lips.
@MainActor
final class CameraController: NSObject, ObservableObject {
    @Published var authorized = false
    @Published var position: AVCaptureDevice.Position = .front
    @Published var quality = QualityReport()
    let session = AVCaptureSession()

    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "camera.frames")
    private var currentInput: AVCaptureDeviceInput?
    // Touched only on `queue`, so we manage the synchronization ourselves.
    private nonisolated(unsafe) let ciContext = CIContext()
    private nonisolated(unsafe) var recording = false
    private nonisolated(unsafe) var buffer: [Data] = []
    private nonisolated(unsafe) var lastKept = CMTime.negativeInfinity
    private nonisolated(unsafe) var lastCheck = CMTime.negativeInfinity
    private let maxSide: CGFloat = 480
    private let targetInterval = 0.039   // ~25 fps to match the model

    private nonisolated(unsafe) var didSetup = false

    /// Set up (once) and start the session. Call from a view's onAppear.
    func configure() async {
        let ok = await Self.requestCameraAccess()
        authorized = ok
        guard ok else { return }
        queue.async { [weak self] in
            guard let self else { return }
            if !self.didSetup { self.didSetup = true; self.setup() }
            if !self.session.isRunning { self.session.startRunning() }
        }
    }

    /// Stop the session when the view leaves the screen, so two tabs don't both
    /// hold the camera (which leaves a frozen preview).
    func stop() {
        queue.async { [weak self] in
            if self?.session.isRunning == true { self?.session.stopRunning() }
        }
    }

    private func setup() {
        session.beginConfiguration()
        session.sessionPreset = .vga640x480
        // Add the output first so addInput() can orient its connection.
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }
        addInput(for: position)
        session.commitConfiguration()
    }

    /// Swap the camera input for the given position and re-orient the output.
    private func addInput(for pos: AVCaptureDevice.Position) {
        if let old = currentInput { session.removeInput(old) }
        guard let cam = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: pos),
              let input = try? AVCaptureDeviceInput(device: cam),
              session.canAddInput(input) else { return }
        session.addInput(input)
        currentInput = input
        if let conn = output.connection(with: .video), conn.isVideoOrientationSupported {
            conn.videoOrientation = .portrait     // upright for both cameras
        }
    }

    /// Flip between front and back camera.
    func flip() {
        let next: AVCaptureDevice.Position = (position == .front) ? .back : .front
        queue.async { [weak self] in
            guard let self else { return }
            self.session.beginConfiguration()
            self.addInput(for: next)
            self.session.commitConfiguration()
            Task { @MainActor in self.position = next }
        }
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
        guard let px = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)

        if recording {
            // Throttle to ~25 fps (the sensor delivers ~30) to match the model.
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
            return
        }

        // Idle: run a lightweight quality check ~1.5x/sec.
        if lastCheck != .negativeInfinity,
           CMTimeGetSeconds(CMTimeSubtract(ts, lastCheck)) < 0.66 { return }
        lastCheck = ts
        analyzeQuality(px)
    }

    /// Estimate framing (face size + centering) and brightness, publish a tip.
    private nonisolated func analyzeQuality(_ px: CVPixelBuffer) {
        let ci = CIImage(cvPixelBuffer: px)
        let brightness = averageLuma(ci)

        let handler = VNImageRequestHandler(cvPixelBuffer: px, orientation: .up)
        let req = VNDetectFaceRectanglesRequest()
        try? handler.perform([req])
        let face = (req.results)?.first

        var report = QualityReport()
        if let box = face?.boundingBox {
            let frac = box.height           // face height / frame height
            if frac < 0.22 { report.tip = "Move closer" }
            else if frac > 0.92 { report.tip = "Move back a little" }
            else if brightness < 0.16 { report.tip = "Too dark — add light on your face" }
            else if brightness > 0.97 { report.tip = "Too bright" }
            else if abs(box.midX - 0.5) > 0.24 || abs(box.midY - 0.5) > 0.30 {
                report.tip = "Center your face"
            } else {
                report.tip = "Good lighting & framing ✓"; report.ok = true
            }
        } else {
            report.tip = brightness < 0.16 ? "Too dark to see a face" : "No face detected — face the camera"
        }
        Task { @MainActor in self.quality = report }
    }

    private nonisolated func averageLuma(_ image: CIImage) -> CGFloat {
        guard let f = CIFilter(name: "CIAreaAverage", parameters: [
            kCIInputImageKey: image,
            kCIInputExtentKey: CIVector(cgRect: image.extent)]),
            let out = f.outputImage else { return 0.5 }
        var px = [UInt8](repeating: 0, count: 4)
        ciContext.render(out, toBitmap: &px, rowBytes: 4,
                         bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                         format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
        return (0.299 * CGFloat(px[0]) + 0.587 * CGFloat(px[1]) + 0.114 * CGFloat(px[2])) / 255.0
    }
}
