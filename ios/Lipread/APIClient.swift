import Foundation

/// Talks to the FastAPI backend, attaching the Supabase access token.
struct APIClient {
    let session: SessionStore

    struct UtterResponse: Decodable {
        let text: String?
        let audio: String?          // base64 WAV
        let audio_mime: String?
        let message: String?
    }

    // MARK: - Teach models

    struct Sentences: Decodable { let sentences: [String] }

    struct JobInfo: Decodable {
        let id: String
        let status: String
        let error: String?
        let log: String?
    }

    struct TeachStatus: Decodable {
        let samples_total: Int
        let new_since_train: Int
        let retrain_threshold: Int
        let active_model_id: String?
        let latest_job: JobInfo?
    }

    struct PracticePhrase: Decodable, Identifiable {
        let id: String
        let text: String
        let reps: Int
    }

    struct Voice: Decodable, Identifiable {
        let id: String
        let name: String
        let slug: String
        let engine: String
        let created_at: Double
        let is_default: Bool
    }

    struct ModelInfo: Decodable {
        let active: String            // "base" | "personal"
        let has_personal: Bool
        let trained_at: Double?
        let n_samples: Int?
        let total_clips: Int
        let distinct_phrases: Int
    }

    enum APIError: LocalizedError {
        case notAuthenticated
        case server(String)
        var errorDescription: String? {
            switch self {
            case .notAuthenticated: return "Not signed in."
            case .server(let m): return m
            }
        }
    }

    private func authorized(_ path: String, method: String = "GET") async throws -> URLRequest {
        guard let token = await session.accessToken() else { throw APIError.notAuthenticated }
        // Build by string so query params (?n=8) aren't percent-escaped into the path.
        guard let url = URL(string: Config.apiBaseURL.absoluteString + "/" + path) else {
            throw APIError.server("bad url")
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return req
    }

    /// POST a push-to-talk clip (JPEG frames) → transcript (+ optional voice).
    func utter(frames: [Data], fps: Int = 25, speak: Bool, cleanup: Bool) async throws -> UtterResponse {
        var req = try await authorized("api/utter", method: "POST")
        let boundary = "Boundary-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = Self.multipart(boundary: boundary, frames: frames, fields: [
            "fps": String(fps),
            "speak": speak ? "true" : "false",
            "cleanup": cleanup ? "true" : "false",
        ])
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(UtterResponse.self, from: data)
    }

    /// POST a labeled clip as a training sample. Returns the new sample id.
    @discardableResult
    func addSample(frames: [Data], phrase: String, fps: Int = 25) async throws -> String {
        struct Out: Decodable { let sample_id: String }
        var req = try await authorized("api/teach/samples", method: "POST")
        let boundary = "Boundary-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = Self.multipart(boundary: boundary, frames: frames,
                                      fields: ["phrase": phrase, "fps": String(fps)])
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(Out.self, from: data).sample_id
    }

    /// Delete a recorded training clip by id (discard a bad take).
    func deleteSample(id: String) async throws {
        let req = try await authorized("api/teach/samples/\(id)", method: "DELETE")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
    }

    // MARK: - Teach

    func teachSentences(n: Int = 8) async throws -> [String] {
        let req = try await authorized("api/teach/sentences?n=\(n)")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(Sentences.self, from: data).sentences
    }

    func teachStatus() async throws -> TeachStatus {
        let req = try await authorized("api/teach/status")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(TeachStatus.self, from: data)
    }

    func teachTrain() async throws -> JobInfo {
        let req = try await authorized("api/teach/train", method: "POST")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(JobInfo.self, from: data)
    }

    func teachPractice() async throws -> [PracticePhrase] {
        let req = try await authorized("api/teach/practice")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode([PracticePhrase].self, from: data)
    }

    /// Queue a sentence to practice/record later (used by "add to training").
    func addPractice(text: String) async throws {
        var req = try await authorized("api/teach/practice", method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(["text": text])
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
    }

    /// Remove a practice phrase from the list.
    func deletePractice(id: String) async throws {
        let req = try await authorized("api/teach/practice/\(id)", method: "DELETE")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
    }

    /// Deactivate the personalized model — Speak reverts to the base model.
    func teachReset() async throws {
        let req = try await authorized("api/teach/reset", method: "POST")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
    }

    // MARK: - Voices

    func listVoices() async throws -> [Voice] {
        let req = try await authorized("api/voices")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode([Voice].self, from: data)
    }

    /// Upload a recorded WAV clip as a new named voice (zero-shot clone).
    func createVoice(name: String, wav: Data, engine: String = "voxcpm") async throws -> Voice {
        var req = try await authorized("api/voices", method: "POST")
        let boundary = "Boundary-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = Self.multipartAudio(boundary: boundary, wav: wav,
                                           fields: ["name": name, "engine": engine])
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(Voice.self, from: data)
    }

    /// Make this voice the active speaker used by Speak.
    func setDefaultVoice(id: String) async throws -> Voice {
        let req = try await authorized("api/voices/\(id)/default", method: "POST")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(Voice.self, from: data)
    }

    func deleteVoice(id: String) async throws {
        let req = try await authorized("api/voices/\(id)", method: "DELETE")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
    }

    /// Fetch the stored reference WAV for preview playback.
    func voiceReference(id: String) async throws -> Data {
        let req = try await authorized("api/voices/\(id)/reference")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return data
    }

    // MARK: - Model

    func modelInfo() async throws -> ModelInfo {
        let req = try await authorized("api/model/info")
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(ModelInfo.self, from: data)
    }

    func modelSelect(usePersonal: Bool) async throws -> ModelInfo {
        var req = try await authorized("api/model/select", method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(["use_personal": usePersonal])
        let (data, resp) = try await URLSession.shared.data(for: req)
        try Self.check(resp, data)
        return try JSONDecoder().decode(ModelInfo.self, from: data)
    }

    // MARK: - helpers

    private static func check(_ resp: URLResponse, _ data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        if !(200..<300).contains(http.statusCode) {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError.server(detail ?? "HTTP \(http.statusCode)")
        }
    }

    private static func multipart(boundary: String, frames: [Data], fields: [String: String]) -> Data {
        var body = Data()
        func append(_ s: String) { body.append(s.data(using: .utf8)!) }
        for (k, v) in fields {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"\(k)\"\r\n\r\n\(v)\r\n")
        }
        for (i, jpeg) in frames.enumerated() {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"frames\"; filename=\"f\(i).jpg\"\r\n")
            append("Content-Type: image/jpeg\r\n\r\n")
            body.append(jpeg)
            append("\r\n")
        }
        append("--\(boundary)--\r\n")
        return body
    }

    private static func multipartAudio(boundary: String, wav: Data, fields: [String: String]) -> Data {
        var body = Data()
        func append(_ s: String) { body.append(s.data(using: .utf8)!) }
        for (k, v) in fields {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"\(k)\"\r\n\r\n\(v)\r\n")
        }
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"audio\"; filename=\"reference.wav\"\r\n")
        append("Content-Type: audio/wav\r\n\r\n")
        body.append(wav)
        append("\r\n")
        append("--\(boundary)--\r\n")
        return body
    }
}
