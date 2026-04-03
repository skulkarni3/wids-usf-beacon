//
//  ChatManager.swift
//  WiDS_WildFire_Navigation
//

import Foundation
import Combine
import CoreLocation

// MARK: - Model

struct ChatAction: Codable, Hashable, Identifiable {
    let id: String
    let label: String
}

struct ChatMessage: Identifiable, Codable {
    let id: UUID
    let role: String       // "user" or "assistant"
    let content: String
    let timestamp: Date
    var actions: [ChatAction]?

    init(role: String, content: String, actions: [ChatAction]? = nil) {
        self.id        = UUID()
        self.role      = role
        self.content   = content
        self.timestamp = Date()
        self.actions   = actions
    }

    enum CodingKeys: String, CodingKey {
        case id, role, content, timestamp, actions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        role = try c.decode(String.self, forKey: .role)
        content = try c.decode(String.self, forKey: .content)
        timestamp = try c.decode(Date.self, forKey: .timestamp)
        actions = try c.decodeIfPresent([ChatAction].self, forKey: .actions)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(role, forKey: .role)
        try c.encode(content, forKey: .content)
        try c.encode(timestamp, forKey: .timestamp)
        try c.encodeIfPresent(actions, forKey: .actions)
    }

    /// Used to produce an updated copy while preserving id and timestamp.
    func withContent(_ newContent: String) -> ChatMessage {
        ChatMessage(id: id, role: role, content: newContent, timestamp: timestamp, actions: actions)
    }

    func withActions(_ newActions: [ChatAction]?) -> ChatMessage {
        ChatMessage(id: id, role: role, content: content, timestamp: timestamp, actions: newActions)
    }

    private init(id: UUID, role: String, content: String, timestamp: Date, actions: [ChatAction]? = nil) {
        self.id        = id
        self.role      = role
        self.content   = content
        self.timestamp = timestamp
        self.actions   = actions
    }
}

// MARK: - Manager

private let messagesKey    = "chat_messages"
private let sessionIDKey   = "chat_session_id"

class ChatManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var messages:   [ChatMessage] = []
    @Published var isLoading:  Bool          = false
    @Published var errorMsg:   String?       = nil
    @Published var scrollTick: Int           = 0   // incremented periodically during streaming

    private var sessionId: String? = nil
    private var isStartingSession  = false   // prevents concurrent session-start calls
    private let locationManager    = CLLocationManager()
    private var locationContinuation: CheckedContinuation<CLLocationCoordinate2D, Error>?
    var settings: SettingsManager?
    var userId: String?

    override init() {
        super.init()
        loadMessages()
        sessionId = UserDefaults.standard.string(forKey: sessionIDKey)
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    // MARK: - Session

    func startSessionIfNeeded() async {
        guard sessionId == nil, !isStartingSession else { return }
        isStartingSession = true
        defer { isStartingSession = false }

        let loc = settingsLocation()
        let ts  = settings?.timestampString ?? ISO8601DateFormatter().string(from: Date())
        try? await startSession(lat: loc.lat, lon: loc.lon, timestamp: ts)
    }

    /// Always uses the stored settings lat/lon (same values shown in SettingsView).
    private func settingsLocation() -> (lat: Double, lon: Double) {
        (lat: settings?.lat ?? AppConstants.defaultLat, lon: settings?.lon ?? AppConstants.defaultLon)
    }

    private func startSession(lat: Double, lon: Double, timestamp: String) async throws {
        print("[Chat] startSession lat=\(lat) lon=\(lon) ts=\(timestamp) overrideEnabled=\(settings?.overrideEnabled ?? false)")
        guard let url = URL(string: "\(settings?.baseURL ?? AppConstants.defaultBaseURL)/chat/session/start") else { return }
        var req = URLRequest(url: url, timeoutInterval: 180)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        struct StartBody: Encodable {
            let lat: Double; let lon: Double; let timestamp: String; let user_id: String?
            let distance: Double; let hwp_threshold: Double
            let hwp_max_fraction: Double; let max_candidates: Int
            let dropby_type: String; let language: String
        }
        let payload = StartBody(
            lat: lat, lon: lon, timestamp: timestamp, user_id: userId,
            distance:         settings?.distance        ?? AppConstants.defaultDistance,
            hwp_threshold:    settings?.hwpThreshold    ?? AppConstants.defaultHwpThreshold,
            hwp_max_fraction: settings?.hwpMaxFraction  ?? AppConstants.defaultHwpMaxFraction,
            max_candidates:   settings?.maxCandidates   ?? AppConstants.defaultMaxCandidates,
            dropby_type:      (settings?.requireDropBy  ?? AppConstants.defaultRequireDropBy) ? "store" : "none",
            language:         settings?.language        ?? "en"
        )
        req.httpBody = try JSONEncoder().encode(payload)

        let (data, _) = try await URLSession.shared.data(for: req)
        let body = try JSONDecoder().decode([String: AnyCodable].self, from: data)
        if let id = body["session_id"]?.value as? String {
            sessionId = id
            UserDefaults.standard.set(id, forKey: sessionIDKey)
        }
        // Logged-in: DB language from server — update local Settings if it differs (new device / web change).
        if let uid = userId, !uid.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           let lang = body["language"]?.value as? String, !lang.isEmpty {
            await MainActor.run { settings?.synchronizeLanguageFromServer(lang) }
        }
        // Save GeoJSON to caches directory if route was computed
        if let geojsonRaw = data.toJSONDictionary()?["geojson"], !(geojsonRaw is NSNull) {
            
            let geojsonData: Data?
            
            // Check if it's already a String (Option A) or a Dictionary that needs encoding
            if let geojsonString = geojsonRaw as? String {
                geojsonData = Data(geojsonString.utf8)
            } else {
                // If it's a Dictionary, encode it to Data
                geojsonData = try? JSONSerialization.data(withJSONObject: geojsonRaw, options: .prettyPrinted)
            }

            if let dataToWrite = geojsonData {
                // Use .cachesDirectory instead of .documentDirectory for temporary map data
                if let cachesURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first {
                    let fileURL = cachesURL.appendingPathComponent("route.geojson")
                    try? dataToWrite.write(to: fileURL)
                    print("[Chat] route.geojson saved to: \(fileURL.path)")
                }
            }
        }
    }

    // MARK: - Send Message

    func send(_ text: String) async {
        guard !text.trimmingCharacters(in: .whitespaces).isEmpty else { return }

        await MainActor.run {
            messages.append(ChatMessage(role: "user", content: text))
            isLoading = true
            errorMsg  = nil
            saveMessages()
        }

        await sendToServer(text)
    }

    private func sendToServer(_ text: String) async {
        let ts  = settings?.timestampString ?? ISO8601DateFormatter().string(from: Date())
        let base = settings?.baseURL ?? AppConstants.defaultBaseURL
        do {
            if sessionId == nil {
                print("[Chat] No session — starting one at \(base)")
                let loc = settingsLocation()
                do {
                    try await startSession(lat: loc.lat, lon: loc.lon, timestamp: ts)
                } catch {
                    print("[Chat] startSession failed: \(error)")
                    await MainActor.run { isLoading = false; errorMsg = "Could not connect to server: \(error.localizedDescription)" }
                    return
                }
            }
            guard let sid = sessionId,
                  let url = URL(string: "\(base)/chat/message") else {
                print("[Chat] No session id or bad URL — base=\(base)")
                await MainActor.run { isLoading = false; errorMsg = "Session unavailable. Check server URL in Settings." }
                return
            }
            print("[Chat] Sending to \(url)")

            var req = URLRequest(url: url, timeoutInterval: 120)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let pref = settings.map { SettingsManager.normalizeLanguageCode($0.language) } ?? "en"
            struct MessageBody: Encodable {
                let session_id: String
                let message: String
                let preferred_language: String
            }
            req.httpBody = try JSONEncoder().encode(
                MessageBody(session_id: sid, message: text, preferred_language: pref)
            )

            let (asyncBytes, response) = try await URLSession.shared.bytes(for: req)

            if let http = response as? HTTPURLResponse, http.statusCode == 404 {
                sessionId = nil
                UserDefaults.standard.removeObject(forKey: sessionIDKey)
                let loc = settingsLocation()
                try? await startSession(lat: loc.lat, lon: loc.lon, timestamp: ts)
                await sendToServer(text)   // retry without re-appending user message
                return
            }

            // Add a placeholder assistant message that we'll update in-place
            let placeholder = ChatMessage(role: "assistant", content: "")
            await MainActor.run {
                messages.append(placeholder)
                isLoading = false   // spinner off — streaming text now visible
            }

            var accumulated = ""
            var charsSinceScroll = 0
            let scrollEvery = 20

            for try await line in asyncBytes.lines {
                guard line.hasPrefix("data: ") else { continue }
                let payload = String(line.dropFirst(6))
                guard payload != "[DONE]" else { break }

                guard let data = payload.data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }

                // Language echo from server — update display language silently (no session reset).
                if let detectedLang = json["language"] as? String {
                    await MainActor.run { settings?.setLanguageSilently(detectedLang) }
                    continue
                }

                // Navigation shortcuts from server (stable ids for MainTabRouter / AuthManager)
                if let rawActions = json["actions"] as? [[String: Any]] {
                    let parsed: [ChatAction] = rawActions.compactMap { dict in
                        guard let id = dict["id"] as? String,
                              let label = dict["label"] as? String else { return nil }
                        return ChatAction(id: id, label: label)
                    }
                    let msgId = placeholder.id
                    await MainActor.run {
                        if let idx = messages.firstIndex(where: { $0.id == msgId }) {
                            messages[idx] = messages[idx].withActions(parsed.isEmpty ? nil : parsed)
                        }
                    }
                    continue
                }

                // Checklist item toggled by agent — tell ChecklistView to re-fetch from server.
                if json["checklist_updated"] as? Bool == true {
                    NotificationCenter.default.post(name: .householdAnswersUpdated, object: nil)
                    continue
                }

                guard let chunk = json["text"] as? String else { continue }

                accumulated += chunk
                charsSinceScroll += chunk.count
                let snapshot  = accumulated
                let msgId     = placeholder.id
                let shouldScroll = charsSinceScroll >= scrollEvery
                if shouldScroll { charsSinceScroll = 0 }
                await MainActor.run {
                    if let idx = messages.firstIndex(where: { $0.id == msgId }) {
                        messages[idx] = messages[idx].withContent(snapshot)
                    }
                    if shouldScroll { scrollTick += 1 }
                }
            }

            await MainActor.run { saveMessages() }

        } catch {
            await MainActor.run {
                // Remove empty placeholder if streaming never started
                if let last = messages.last, last.role == "assistant", last.content.isEmpty {
                    messages.removeLast()
                }
                errorMsg  = "Failed to send message."
                isLoading = false
            }
            return
        }

        await MainActor.run { isLoading = false }
    }

    // MARK: - Persistence

    func clearHistory() {
        messages          = []
        sessionId         = nil
        isStartingSession = false
        UserDefaults.standard.removeObject(forKey: messagesKey)
        UserDefaults.standard.removeObject(forKey: sessionIDKey)
    }

    private func saveMessages() {
        if let data = try? JSONEncoder().encode(messages) {
            UserDefaults.standard.set(data, forKey: messagesKey)
        }
    }

    private func loadMessages() {
        guard let data = UserDefaults.standard.data(forKey: messagesKey),
              let saved = try? JSONDecoder().decode([ChatMessage].self, from: data)
        else { return }
        messages = saved
    }

    // MARK: - Location

    private func requestLocation() async throws -> CLLocationCoordinate2D {
        return try await withCheckedThrowingContinuation { continuation in
            self.locationContinuation = continuation
            switch locationManager.authorizationStatus {
            case .authorizedWhenInUse, .authorizedAlways:
                locationManager.requestLocation()
            case .notDetermined:
                locationManager.requestWhenInUseAuthorization()
            default:
                continuation.resume(throwing: NSError(domain: "Location", code: 1))
            }
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let coord = locations.first?.coordinate else { return }
        locationContinuation?.resume(returning: coord)
        locationContinuation = nil
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        locationContinuation?.resume(throwing: error)
        locationContinuation = nil
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedWhenInUse, .authorizedAlways:
            manager.requestLocation()
        case .denied, .restricted:
            // Resume with error so requestLocation() doesn't hang forever
            locationContinuation?.resume(throwing: NSError(domain: "Location", code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Location access denied"]))
            locationContinuation = nil
        default:
            break
        }
    }
}

// MARK: - Data helper

private extension Data {
    func toJSONDictionary() -> [String: Any]? {
        try? JSONSerialization.jsonObject(with: self) as? [String: Any]
    }
}

// MARK: - AnyCodable helper

struct AnyCodable: Codable {
    let value: Any
    init(_ value: Any) { self.value = value }
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let v = try? c.decode(String.self)  { value = v; return }
        if let v = try? c.decode(Double.self)  { value = v; return }
        if let v = try? c.decode(Bool.self)    { value = v; return }
        if let v = try? c.decode(Int.self)     { value = v; return }
        value = ""
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        if let v = value as? String { try c.encode(v) }
        else if let v = value as? Double { try c.encode(v) }
        else if let v = value as? Bool   { try c.encode(v) }
        else if let v = value as? Int    { try c.encode(v) }
    }
}
