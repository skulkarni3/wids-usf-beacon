//
//  SettingsView.swift
//  WiDS_WildFire_Navigation
//

import SwiftUI

let supportedLanguages: [(code: String, name: String)] = [
    ("en", "English"),
    // Americas
    ("es", "Español"),
    ("pt", "Português"),
    ("ht", "Kreyòl Ayisyen"),
    // East & Southeast Asia
    ("zh", "中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("vi", "Tiếng Việt"),
    ("tl", "Filipino"),
    ("th", "ภาษาไทย"),
    ("km", "ភាសាខ្មែរ"),
    ("lo", "ລາວ"),
    ("my", "မြန်မာဘာသာ"),
    ("id", "Bahasa Indonesia"),
    ("ms", "Bahasa Melayu"),
    ("hmn", "Hmoob"),
    // South Asia
    ("hi", "हिन्दी"),
    ("ur", "اردو"),
    ("bn", "বাংলা"),
    ("pa", "ਪੰਜਾਬੀ"),
    ("gu", "ગુજરાતી"),
    // Middle East & Central Asia
    ("ar", "العربية"),
    ("fa", "فارسی"),
    ("tr", "Türkçe"),
    // Europe
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("it", "Italiano"),
    ("ru", "Русский"),
    ("uk", "Українська"),
    ("pl", "Polski"),
    ("nl", "Nederlands"),
    ("ro", "Română"),
    ("el", "Ελληνικά"),
    // Africa
    ("sw", "Kiswahili"),
    ("am", "አማርኛ"),
    ("so", "Soomaali"),
    ("yo", "Yorùbá"),
    ("ha", "Hausa"),
]

struct SettingsView: View {
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var translations: TranslationManager
    @EnvironmentObject var auth: AuthManager

    private let green = Color(red: 185/255, green: 58/255, blue: 18/255)
    private let gold  = Color(red: 205/255, green: 163/255, blue: 35/255)

    @State private var latText: String = ""
    @State private var lonText: String = ""
    @State private var distanceText:       String = ""
    @State private var hwpThresholdText:   String = ""
    @State private var hwpMaxFractionText: String = ""
    @State private var maxCandidatesText:  String = ""
    @State private var localTimestamp:     Date   = Date()
    @State private var localLanguage:      String = "en"
    @State private var localBaseURL:       String = AppConstants.defaultBaseURL
    @State private var localRequireDropBy: Bool   = AppConstants.defaultRequireDropBy
    @State private var localOverride:      Bool   = false
    @FocusState private var anyFieldFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text(translations.t("Demo Settings"))
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
            }
            .padding()
            .background(green)

            Form {
                Section(header: Text(translations.t("Account"))) {
                    Button {
                        auth.openOnboardingEditor()
                    } label: {
                        Label(translations.t("Update onboarding answers"), systemImage: "person.crop.circle.badge.questionmark")
                    }
                    .foregroundColor(green)

                    Button(role: .destructive) {
                        auth.logout()
                    } label: {
                        Label(translations.t("Log out"), systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }

                Section(header: Text(translations.t("Language"))) {
                    Picker(translations.t("Language"), selection: $localLanguage) {
                        ForEach(supportedLanguages, id: \.code) { lang in
                            Text(lang.name).tag(lang.code)
                        }
                    }
                    .pickerStyle(.menu)
                    .onChange(of: localLanguage) { _, val in
                        if val != settings.language { settings.language = val }
                    }
                }

                Section(
                    header: Text(translations.t("Server")),
                    footer: Text(translations.t("Run `ipconfig getifaddr en0` on your Mac to get the current IP."))
                ) {
                    TextField(AppConstants.defaultBaseURL, text: $localBaseURL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .onChange(of: localBaseURL) { _, val in
                            if val != settings.baseURL { settings.baseURL = val }
                        }
                }

                Section(header: Text(translations.t("Route Options"))) {
                    Toggle(translations.t("Require Drop-By Store on Route"), isOn: $localRequireDropBy)
                        .tint(green)
                        .onChange(of: localRequireDropBy) { _, val in
                            if val != settings.requireDropBy { settings.requireDropBy = val }
                        }
                }

                Section(
                    header: Text(translations.t("Route Parameters")),
                    footer: Text(translations.t("Distance in meters. Defaults: \(Int(AppConstants.defaultDistance)) m, threshold \(Int(AppConstants.defaultHwpThreshold)), max fraction \(AppConstants.defaultHwpMaxFraction), candidates \(AppConstants.defaultMaxCandidates)."))
                ) {
                    HStack {
                        Text(translations.t("Distance (m)")).foregroundColor(.secondary)
                        Spacer()
                        TextField(String(AppConstants.defaultDistance), text: $distanceText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .focused($anyFieldFocused)
                            .onChange(of: distanceText) { _, val in
                                if let d = Double(val) { settings.distance = d }
                            }
                    }
                    HStack {
                        Text(translations.t("HWP Threshold")).foregroundColor(.secondary)
                        Spacer()
                        TextField(String(AppConstants.defaultHwpThreshold), text: $hwpThresholdText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .focused($anyFieldFocused)
                            .onChange(of: hwpThresholdText) { _, val in
                                if let d = Double(val) { settings.hwpThreshold = d }
                            }
                    }
                    HStack {
                        Text(translations.t("HWP Max Fraction")).foregroundColor(.secondary)
                        Spacer()
                        TextField(String(AppConstants.defaultHwpMaxFraction), text: $hwpMaxFractionText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .focused($anyFieldFocused)
                            .onChange(of: hwpMaxFractionText) { _, val in
                                if let d = Double(val) { settings.hwpMaxFraction = d }
                            }
                    }
                    HStack {
                        Text(translations.t("Max Candidates")).foregroundColor(.secondary)
                        Spacer()
                        TextField(String(AppConstants.defaultMaxCandidates), text: $maxCandidatesText)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .focused($anyFieldFocused)
                            .onChange(of: maxCandidatesText) { _, val in
                                if let i = Int(val) { settings.maxCandidates = i }
                            }
                    }
                }

                Section(
                    footer: Text(translations.t("When enabled, the app uses the values below instead of your real GPS and current time."))
                ) {
                    Toggle(translations.t("Override Location & Time"), isOn: $localOverride)
                        .tint(green)
                        .onChange(of: localOverride) { _, val in
                            if val != settings.overrideEnabled { settings.overrideEnabled = val }
                        }
                }

                Section(header: Text(translations.t("Location"))) {
                    HStack {
                        Text(translations.t("Latitude"))
                            .foregroundColor(.secondary)
                        Spacer()
                        TextField(String(AppConstants.defaultLat), text: $latText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .focused($anyFieldFocused)
                            .onChange(of: latText) { _, val in
                                if let d = Double(val) { settings.lat = d }
                            }
                    }
                    HStack {
                        Text(translations.t("Longitude"))
                            .foregroundColor(.secondary)
                        Spacer()
                        TextField(String(AppConstants.defaultLon), text: $lonText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .focused($anyFieldFocused)
                            .onChange(of: lonText) { _, val in
                                if let d = Double(val) { settings.lon = d }
                            }
                    }
                }
                .disabled(!localOverride)

                Section(header: Text(translations.t("Timestamp"))) {
                    DatePicker(translations.t("Date & Time"),
                               selection: $localTimestamp,
                               displayedComponents: [.date, .hourAndMinute])
                        .tint(green)
                        .disabled(!localOverride)
                        .onChange(of: localTimestamp) { _, val in
                            if val != settings.timestamp { settings.timestamp = val }
                        }
                }

Section {
                    Button(translations.t("Reset to Defaults")) {
                        settings.lat            = AppConstants.defaultLat
                        settings.lon            = AppConstants.defaultLon
                        settings.timestamp      = AppConstants.defaultTimestamp
                        settings.distance       = AppConstants.defaultDistance
                        settings.hwpThreshold   = AppConstants.defaultHwpThreshold
                        settings.hwpMaxFraction = AppConstants.defaultHwpMaxFraction
                        settings.maxCandidates  = AppConstants.defaultMaxCandidates
                        settings.requireDropBy  = AppConstants.defaultRequireDropBy
                        latText             = String(AppConstants.defaultLat)
                        lonText             = String(AppConstants.defaultLon)
                        distanceText        = String(AppConstants.defaultDistance)
                        hwpThresholdText    = String(AppConstants.defaultHwpThreshold)
                        hwpMaxFractionText  = String(AppConstants.defaultHwpMaxFraction)
                        maxCandidatesText   = String(AppConstants.defaultMaxCandidates)
                        localTimestamp      = AppConstants.defaultTimestamp
                        localRequireDropBy  = AppConstants.defaultRequireDropBy
                    }
                    .foregroundColor(.red)
                    .disabled(!localOverride)
                }


            }
            .scrollDismissesKeyboard(.interactively)
        }
        .onAppear {
            latText             = String(settings.lat)
            lonText             = String(settings.lon)
            distanceText        = String(settings.distance)
            hwpThresholdText    = String(settings.hwpThreshold)
            hwpMaxFractionText  = String(settings.hwpMaxFraction)
            maxCandidatesText   = String(settings.maxCandidates)
            localTimestamp      = settings.timestamp
            localLanguage       = settings.language
            localBaseURL        = settings.baseURL
            localRequireDropBy  = settings.requireDropBy
            localOverride       = settings.overrideEnabled
        }
        .onChange(of: settings.language) { _, code in
            Task { await patchLanguagePreference(userId: auth.userId, baseURL: settings.baseURL, code: code) }
        }
    }
}

/// Persists confirmed language to Postgres (`PATCH /user/preferences/language`). No-op if not logged in.
private func patchLanguagePreference(userId: String?, baseURL: String, code: String) async {
    guard let uid = userId?.trimmingCharacters(in: .whitespacesAndNewlines), !uid.isEmpty else { return }
    let base = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !base.isEmpty else { return }
    let lang = SettingsManager.normalizeLanguageCode(code)
    guard var c = URLComponents(string: "\(base)/user/preferences/language") else { return }
    c.queryItems = [
        URLQueryItem(name: "user_id", value: uid),
        URLQueryItem(name: "language", value: lang),
    ]
    guard let url = c.url else { return }
    var req = URLRequest(url: url)
    req.httpMethod = "PATCH"
    _ = try? await URLSession.shared.data(for: req)
}
