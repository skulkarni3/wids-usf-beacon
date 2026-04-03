//
//  TranslationManager.swift
//  WiDS_WildFire_Navigation
//
//  Fetches UI translations from the backend when the language changes,
//  caches them in UserDefaults, and exposes a t() lookup used by all views.
//

import Foundation
import Combine

class TranslationManager: ObservableObject {

    /// All translated strings for the current language. Empty = use English fallback.
    @Published private(set) var table: [String: String] = [:]

    /// True while a translation fetch is in progress.
    @Published private(set) var isLoading = false

    private var cancellables = Set<AnyCancellable>()
    private var settings: SettingsManager?

    // All English UI strings that need translating
    static let uiStrings: [String] = [
        // ChatView
        "Beacon AI Agent",
        // SettingsView
        "Demo Settings",
        "Server",
        "Run `ipconfig getifaddr en0` on your Mac to get the current IP.",
        "Route Options",
        "Require Drop-By Store on Route",
        "Route Parameters",
        "Distance in meters. Defaults: 50000 m, threshold 50, max fraction 0.1, candidates 100.",
        "Distance (m)",
        "HWP Threshold",
        "HWP Max Fraction",
        "Max Candidates",
        "When enabled, the app uses the values below instead of your real GPS and current time.",
        "Override Location & Time",
        "Location",
        "Latitude",
        "Longitude",
        "Timestamp",
        "Date & Time",
        "Reset to Defaults",
        "Active Override",
        "Language",
        // ChecklistView
        "Onboarding",
        "Evacuation checklist",
        "Submitting...",
        "Submit Onboarding",
        "Save onboarding answers",
        "Update onboarding",
        "Close",
        "No checklist available",
        "Retry",
        // SettingsView — account section
        "Account",
        "Update onboarding answers",
        "Log out",
        // ContentView (map tab status messages)
        "Tap the Map tab to fetch your evacuation route.",
        "Fetching evacuation route\u{2026}",
        "Calculating evacuation route\u{2026}",
        "Navigation Paused",
        "Resume",
        "Stop",
        "Resuming navigation\u{2026}",
        "Recalculating route\u{2026}",
        "No evacuation route found",
        "Could not start navigation",
        // LoginView
        "WiDS Wildfire Navigation",
        "Email",
        "Password",
        "Log In",
        "Don't have an account? Register",
        // RegisterView
        "Create Account",
        "Name",
        "Address (optional)",
        "Confirm Password",
        "Passwords do not match",
        "Register",
        "Already have an account? Log in",
    ]

    /// Look up a translated string. Falls back to the original English if not found.
    func t(_ english: String) -> String {
        table[english] ?? english
    }

    /// Attach to a SettingsManager and start observing language changes.
    func attach(to settings: SettingsManager) {
        self.settings = settings

        // Load any previously cached table for the current language
        loadCache(for: settings.language)

        // Observe future language changes (works for both user changes and silent AI detection)
        settings.$language
            .removeDuplicates()
            .sink { [weak self] lang in
                self?.fetchTranslations(language: lang, baseURL: settings.baseURL)
            }
            .store(in: &cancellables)

        // Fetch on first launch if non-English and no cache yet
        if settings.language != "en" && table.isEmpty {
            fetchTranslations(language: settings.language, baseURL: settings.baseURL)
        }
    }

    // MARK: - Fetch

    private func fetchTranslations(language: String, baseURL: String) {
        guard language != "en" else {
            table = [:]   // English — use fallback strings directly
            return
        }

        // Return cached version immediately while re-fetching in background
        loadCache(for: language)

        isLoading = true

        guard let url = URL(string: "\(baseURL)/translate") else {
            isLoading = false
            return
        }

        let body: [String: Any] = [
            "language": language,
            "strings": Self.uiStrings
        ]

        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTaskPublisher(for: request)
            .map(\.data)
            .tryMap { data -> [String: String] in
                guard let dict = try JSONSerialization.jsonObject(with: data) as? [String: String] else {
                    throw URLError(.cannotParseResponse)
                }
                return dict
            }
            .receive(on: DispatchQueue.main)
            .sink(receiveCompletion: { [weak self] completion in
                self?.isLoading = false
                if case .failure(let err) = completion {
                    print("[TranslationManager] fetch failed: \(err)")
                }
            }, receiveValue: { [weak self] translations in
                guard let self else { return }
                self.table = translations
                self.saveCache(translations, for: language)
            })
            .store(in: &cancellables)
    }

    // MARK: - Cache

    private func cacheKey(for language: String) -> String { "ui_translations_\(language)" }

    private func loadCache(for language: String) {
        guard language != "en",
              let data = UserDefaults.standard.data(forKey: cacheKey(for: language)),
              let dict = try? JSONDecoder().decode([String: String].self, from: data)
        else {
            table = [:]
            return
        }
        table = dict
    }

    private func saveCache(_ translations: [String: String], for language: String) {
        if let data = try? JSONEncoder().encode(translations) {
            UserDefaults.standard.set(data, forKey: cacheKey(for: language))
        }
    }
}
