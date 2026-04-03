//
//  SettingsManager.swift
//  WiDS_WildFire_Navigation
//

import Foundation
import Combine

private let kOverrideEnabled  = "demo_override_enabled"
private let kOverrideLat      = "demo_lat"
private let kOverrideLon      = "demo_lon"
private let kOverrideDate     = "demo_date"
private let kBaseURL          = "base_url"
private let kDefaultBaseURL   = AppConstants.defaultBaseURL
private let kRequireDropBy    = "require_drop_by"
private let kDistance         = "route_distance"
private let kHwpThreshold     = "route_hwp_threshold"
private let kHwpMaxFraction   = "route_hwp_max_fraction"
private let kMaxCandidates    = "route_max_candidates"
private let kLanguage         = "detected_language"

class SettingsManager: ObservableObject {
    /// Incremented when a setting changes that should reset the **server** chat session + history
    /// (location, route params, server URL, etc.). **Not** language — that is sent on each message
    /// as `preferred_language` and must not wipe the transcript.
    @Published var sessionVersion: Int = 0

    @Published var overrideEnabled: Bool {
        didSet { guard overrideEnabled != oldValue else { return }; UserDefaults.standard.set(overrideEnabled, forKey: kOverrideEnabled); sessionVersion += 1 }
    }
    @Published var lat: Double {
        didSet { guard lat != oldValue else { return }; UserDefaults.standard.set(lat, forKey: kOverrideLat); sessionVersion += 1 }
    }
    @Published var lon: Double {
        didSet { guard lon != oldValue else { return }; UserDefaults.standard.set(lon, forKey: kOverrideLon); sessionVersion += 1 }
    }
    @Published var timestamp: Date {
        didSet { guard timestamp != oldValue else { return }; UserDefaults.standard.set(timestamp, forKey: kOverrideDate); sessionVersion += 1 }
    }
    @Published var baseURL: String {
        didSet { guard baseURL != oldValue else { return }; UserDefaults.standard.set(baseURL, forKey: kBaseURL); sessionVersion += 1 }
    }
    @Published var requireDropBy: Bool {
        didSet { guard requireDropBy != oldValue else { return }; UserDefaults.standard.set(requireDropBy, forKey: kRequireDropBy); sessionVersion += 1 }
    }
    @Published var distance: Double {
        didSet { guard distance != oldValue else { return }; UserDefaults.standard.set(distance, forKey: kDistance); sessionVersion += 1 }
    }
    @Published var hwpThreshold: Double {
        didSet { guard hwpThreshold != oldValue else { return }; UserDefaults.standard.set(hwpThreshold, forKey: kHwpThreshold); sessionVersion += 1 }
    }
    @Published var hwpMaxFraction: Double {
        didSet { guard hwpMaxFraction != oldValue else { return }; UserDefaults.standard.set(hwpMaxFraction, forKey: kHwpMaxFraction); sessionVersion += 1 }
    }
    @Published var maxCandidates: Int {
        didSet { guard maxCandidates != oldValue else { return }; UserDefaults.standard.set(maxCandidates, forKey: kMaxCandidates); sessionVersion += 1 }
    }
    /// UI language (ISO 639-1 code, e.g. "en", "es"). Defaults to device locale; user can override in Settings.
    /// Does NOT increment sessionVersion — language is sent per-message and must not wipe the transcript.
    @Published var language: String {
        didSet { guard language != oldValue else { return }; UserDefaults.standard.set(language, forKey: kLanguage) }
    }

    /// Updates language for display/translation without touching sessionVersion.
    /// Safe to call from streaming AI responses (language SSE echo).
    func setLanguageSilently(_ code: String) {
        let n = Self.normalizeLanguageCode(code)
        guard n != language else { return }
        language = n   // @Published setter handles UserDefaults + objectWillChange; no sessionVersion bump
    }

    /// Incremented each time the user taps the Map tab — used to trigger a route refresh.
    @Published var mapTabTapCount: Int = 0

    init() {
        overrideEnabled  = UserDefaults.standard.bool(forKey: kOverrideEnabled)
        lat              = UserDefaults.standard.object(forKey: kOverrideLat)  as? Double ?? AppConstants.defaultLat
        lon              = UserDefaults.standard.object(forKey: kOverrideLon)  as? Double ?? AppConstants.defaultLon
        timestamp        = UserDefaults.standard.object(forKey: kOverrideDate) as? Date   ?? AppConstants.defaultTimestamp
        baseURL          = UserDefaults.standard.string(forKey: kBaseURL)      ?? kDefaultBaseURL
        requireDropBy    = UserDefaults.standard.object(forKey: kRequireDropBy) as? Bool   ?? AppConstants.defaultRequireDropBy
        distance         = UserDefaults.standard.object(forKey: kDistance)      as? Double ?? AppConstants.defaultDistance
        hwpThreshold     = UserDefaults.standard.object(forKey: kHwpThreshold)  as? Double ?? AppConstants.defaultHwpThreshold
        hwpMaxFraction   = UserDefaults.standard.object(forKey: kHwpMaxFraction) as? Double ?? AppConstants.defaultHwpMaxFraction
        maxCandidates    = UserDefaults.standard.object(forKey: kMaxCandidates)  as? Int    ?? AppConstants.defaultMaxCandidates
        let deviceLang   = Locale.current.language.languageCode?.identifier ?? "en"
        _language        = Published(wrappedValue: UserDefaults.standard.string(forKey: kLanguage) ?? deviceLang)
    }

    /// Returns the effective (lat, lon) — overridden or nil (use real GPS).
    var effectiveLocation: (lat: Double, lon: Double)? {
        overrideEnabled ? (lat, lon) : nil
    }

    /// ISO-8601 string for passing to the backend. Always uses the stored timestamp.
    var timestampString: String {
        ISO8601DateFormatter().string(from: timestamp)
    }

    /// ISO 639-1 (or short prefix) for API payloads.
    static func normalizeLanguageCode(_ code: String) -> String {
        let t = code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !t.isEmpty else { return "en" }
        return t.split(separator: "-").first.map(String.init) ?? t
    }

    /// Align local picker with `POST /chat/session/start` when the server has a stored preference (logged-in only).
    func synchronizeLanguageFromServer(_ code: String) {
        let n = Self.normalizeLanguageCode(code)
        guard n != language else { return }
        language = n
    }
}
