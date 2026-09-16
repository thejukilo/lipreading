import AVFoundation
import SwiftUI

/// SwiftUI wrapper around an AVCaptureVideoPreviewLayer.
struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    /// Mirror the preview (front camera reads like a mirror; back camera must not).
    var mirrored: Bool = true

    func makeUIView(context: Context) -> PreviewView {
        let v = PreviewView()
        v.videoPreviewLayer.session = session
        v.videoPreviewLayer.videoGravity = .resizeAspectFill
        apply(v)
        return v
    }

    func updateUIView(_ uiView: PreviewView, context: Context) { apply(uiView) }

    private func apply(_ v: PreviewView) {
        if let conn = v.videoPreviewLayer.connection, conn.isVideoMirroringSupported {
            conn.automaticallyAdjustsVideoMirroring = false
            conn.isVideoMirrored = mirrored
        }
    }

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var videoPreviewLayer: AVCaptureVideoPreviewLayer {
            layer as! AVCaptureVideoPreviewLayer
        }
    }
}

/// A small pill showing live camera-quality feedback (framing/lighting).
struct QualityBadge: View {
    let quality: QualityReport
    var body: some View {
        Text(quality.tip)
            .font(.caption.bold())
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(quality.ok ? Color.green.opacity(0.85) : Color.orange.opacity(0.9))
            .foregroundStyle(.white)
            .clipShape(.capsule)
    }
}
