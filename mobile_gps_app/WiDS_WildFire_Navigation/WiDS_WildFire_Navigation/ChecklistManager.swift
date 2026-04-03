//
//  ChecklistManager.swift
//  WiDS_WildFire_Navigation
//

import Foundation
import Combine

extension Notification.Name {
    static let onboardingCompleted = Notification.Name("onboardingCompleted")
    /// Posted after household answers are saved from Settings → update onboarding flow.
    static let householdAnswersUpdated = Notification.Name("householdAnswersUpdated")
}

// MARK: - Models

struct ChecklistItem: Identifiable, Codable, Equatable {
    let id: String
    var title: String
    var checked: Bool
}

struct ChecklistCategory: Identifiable, Codable {
    var id: String { title }
    var title: String
    var items: [ChecklistItem]
}

private struct ChecklistFetchResponse: Codable {
    let mode: String
    let categories: [ChecklistCategory]
}

enum ChecklistTabMode: String {
    case onboarding
    case evacuation
}

// MARK: - Manager

/// Bumped when API shape changes so stale “Pets / Medication” cache is not reused.
private let kChecklistKey = "checklist_categories_v2"
private let kChecklistModeKey = "checklist_tab_mode_v2"

class ChecklistManager: ObservableObject {
    @Published var categories: [ChecklistCategory] = []
    @Published var tabMode: ChecklistTabMode = .onboarding
    @Published var isLoading  = false
    @Published var isSubmittingOnboarding = false
    @Published var errorMsg: String? = nil
    /// True while editing onboarding from Settings — do not fire first-time completion handlers.
    var isOnboardingEditorSession: Bool = false

    var settings: SettingsManager?
    var userId: String?

    init() {
        loadLocal()
    }

    // MARK: - Fetch

    func fetchIfNeeded() async {
        if categories.isEmpty { await fetch() }
    }

    /// Load the anonymous onboarding template and merge saved answers from GET /onboarding/household.
    func prepareOnboardingEdit() async {
        await MainActor.run { isLoading = true; errorMsg = nil; categories = [] }
        do {
            guard let uid = userId, !uid.isEmpty else {
                throw URLError(.userAuthenticationRequired)
            }
            let answers = (try? await apiGetHousehold(userID: uid)) ?? HouseholdAnswers()
            let built = Self.householdQuestionCategories(from: answers)
            let translated = await translateCategories(built)
            await MainActor.run {
                categories = translated
                tabMode = .onboarding
                isLoading = false
            }
        } catch {
            await MainActor.run {
                isLoading = false
                errorMsg = "Could not load onboarding for editing: \(error.localizedDescription)"
            }
        }
    }

    /// Builds the household yes/no question list directly from saved answers.
    private static func householdQuestionCategories(from answers: HouseholdAnswers) -> [ChecklistCategory] {
        [
            ChecklistCategory(title: "My Home", items: [
                ChecklistItem(id: "owns_home",     title: "I own my home",                      checked: answers.ownsHome     == true),
                ChecklistItem(id: "has_car",       title: "I have a car",                       checked: answers.hasCar       == true),
                ChecklistItem(id: "has_garage",    title: "I have a garage",                    checked: answers.hasGarage    == true),
                ChecklistItem(id: "has_driveway",  title: "I have a driveway",                  checked: answers.hasDriveway  == true),
                ChecklistItem(id: "has_pool",      title: "I have a pool",                      checked: answers.hasPool      == true),
                ChecklistItem(id: "has_well",      title: "I have a well",                      checked: answers.hasWell      == true),
                ChecklistItem(id: "has_generator", title: "I have a generator",                 checked: answers.hasGenerator == true),
            ]),
            ChecklistCategory(title: "My Household", items: [
                ChecklistItem(id: "has_children",  title: "I have children in my household",    checked: answers.hasChildren  == true),
                ChecklistItem(id: "has_seniors",   title: "I have seniors in my household",     checked: answers.hasSeniors   == true),
                ChecklistItem(id: "has_disabled",  title: "I have household members with disabilities", checked: answers.hasDisabled == true),
            ]),
            ChecklistCategory(title: "Animals", items: [
                ChecklistItem(id: "has_pets",      title: "I have pets",                        checked: answers.hasPets      == true),
                ChecklistItem(id: "has_livestock", title: "I have livestock",                   checked: answers.hasLivestock == true),
            ]),
        ]
    }

    private static func checkedForHouseholdItem(answers: HouseholdAnswers, itemId: String) -> Bool {
        switch itemId {
        case "owns_home":     return answers.ownsHome == true
        case "has_car":       return answers.hasCar == true
        case "has_garage":    return answers.hasGarage == true
        case "has_driveway":  return answers.hasDriveway == true
        case "has_pool":      return answers.hasPool == true
        case "has_well":      return answers.hasWell == true
        case "has_generator": return answers.hasGenerator == true
        case "has_pets":      return answers.hasPets == true
        case "has_livestock": return answers.hasLivestock == true
        case "has_children":  return answers.hasChildren == true
        case "has_seniors":   return answers.hasSeniors == true
        case "has_disabled":  return answers.hasDisabled == true
        default: return false
        }
    }

    func fetch() async {
        await MainActor.run { isLoading = true; errorMsg = nil }
        do {
            let (fetched, mode) = try await apiGetChecklist()
            let translated = await translateCategories(fetched)
            saveToCaches(translated)
            await MainActor.run {
                categories = translated
                tabMode = mode
                isLoading = false
                saveLocal()
            }
        } catch {
            await MainActor.run {
                isLoading = false
                errorMsg  = "Could not load checklist: \(error.localizedDescription)"
            }
        }
    }

    // MARK: - Translation

    private func translateCategories(_ cats: [ChecklistCategory]) async -> [ChecklistCategory] {
        guard let lang = settings?.language, lang != "en" else { return cats }

        // Collect all unique strings to translate
        var strings: [String] = []
        for cat in cats {
            strings.append(cat.title)
            for item in cat.items { strings.append(item.title) }
        }
        let unique = Array(Set(strings))

        guard let table = try? await apiTranslate(strings: unique, language: lang) else {
            return cats
        }

        // Rebuild categories with translated titles
        return cats.map { cat in
            var c = cat
            c.title = table[cat.title] ?? cat.title
            c.items = cat.items.map { item in
                var i = item
                i.title = table[item.title] ?? item.title
                return i
            }
            return c
        }
    }

    private func apiTranslate(strings: [String], language: String) async throws -> [String: String] {
        guard let url = URL(string: "\(baseURL)/translate") else { throw URLError(.badURL) }
        var req = URLRequest(url: url, timeoutInterval: 30)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["language": language, "strings": strings])
        let (data, _) = try await URLSession.shared.data(for: req)
        guard let dict = try JSONSerialization.jsonObject(with: data) as? [String: String] else {
            throw URLError(.cannotParseResponse)
        }
        return dict
    }

    // MARK: - Toggle

    func toggle(itemID: String, in categoryTitle: String) {
        guard let ci = categories.firstIndex(where: { $0.title == categoryTitle }),
              let ii = categories[ci].items.firstIndex(where: { $0.id == itemID })
        else { return }

        categories[ci].items[ii].checked.toggle()
        let newValue = categories[ci].items[ii].checked
        saveLocal()

        Task {
            if tabMode != .onboarding {
                try? await apiPatchItem(itemID: itemID, checked: newValue)
            }
        }
    }

    /// Saves household answers. Returns `true` on success.
    @discardableResult
    func submitOnboarding() async -> Bool {
        guard tabMode == .onboarding else { return false }
        guard let uid = userId, !uid.isEmpty else {
            await MainActor.run {
                errorMsg = "Please sign in before submitting onboarding."
            }
            return false
        }

        await MainActor.run {
            isSubmittingOnboarding = true
            errorMsg = nil
        }

        do {
            let answers = householdAnswersFromCategories()
            try await postHouseholdAnswers(answers)
            await MainActor.run {
                isSubmittingOnboarding = false
            }
            if isOnboardingEditorSession {
                NotificationCenter.default.post(name: .householdAnswersUpdated, object: nil)
            } else {
                await fetch()
                NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
            }
            return true
        } catch {
            await MainActor.run {
                isSubmittingOnboarding = false
                errorMsg = "Could not submit onboarding: \(error.localizedDescription)"
            }
            return false
        }
    }

    /// Maps checklist rows (snake_case ids) → API body for household upsert.
    private func householdAnswersFromCategories() -> HouseholdAnswers {
        var a = HouseholdAnswers()
        for c in categories {
            for item in c.items {
                switch item.id {
                case "owns_home":     a.ownsHome     = item.checked
                case "has_car":       a.hasCar       = item.checked
                case "has_garage":    a.hasGarage    = item.checked
                case "has_driveway":  a.hasDriveway  = item.checked
                case "has_pool":      a.hasPool      = item.checked
                case "has_well":      a.hasWell      = item.checked
                case "has_generator": a.hasGenerator = item.checked
                case "has_pets":      a.hasPets      = item.checked
                case "has_livestock": a.hasLivestock = item.checked
                case "has_children":  a.hasChildren  = item.checked
                case "has_seniors":   a.hasSeniors   = item.checked
                case "has_disabled":  a.hasDisabled  = item.checked
                default: break
                }
            }
        }
        return a
    }

    // MARK: - Local persistence

    private static var cacheFileURL: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("checklist.json")
    }

    private func saveLocal() {
        if let data = try? JSONEncoder().encode(categories) {
            UserDefaults.standard.set(data, forKey: kChecklistKey)
        }
        UserDefaults.standard.set(tabMode.rawValue, forKey: kChecklistModeKey)
    }

    private func saveToCaches(_ categories: [ChecklistCategory]) {
        if let data = try? JSONEncoder().encode(categories) {
            try? data.write(to: Self.cacheFileURL)
        }
    }

    private func loadLocal() {
        if let data = UserDefaults.standard.data(forKey: kChecklistKey),
           let saved = try? JSONDecoder().decode([ChecklistCategory].self, from: data) {
            categories = saved
        }
        if let m = UserDefaults.standard.string(forKey: kChecklistModeKey),
           let mode = ChecklistTabMode(rawValue: m) {
            tabMode = mode
        }
        if !categories.isEmpty { return }
        if let data = try? Data(contentsOf: Self.cacheFileURL),
           let cached = try? JSONDecoder().decode([ChecklistCategory].self, from: data) {
            categories = cached
        }
    }

    // MARK: - API

    private var baseURL: String {
        settings?.baseURL ?? AppConstants.defaultBaseURL
    }

    /// Onboarding question template only (no user_id).
    private func apiGetChecklistTemplate() async throws -> ([ChecklistCategory], ChecklistTabMode) {
        guard let url = URL(string: "\(baseURL)/checklist") else {
            throw URLError(.badURL)
        }
        let (data, _) = try await URLSession.shared.data(from: url)
        let decoded = try JSONDecoder().decode(ChecklistFetchResponse.self, from: data)
        let mode = ChecklistTabMode(rawValue: decoded.mode) ?? .onboarding
        return (decoded.categories, mode)
    }

    private func apiGetHousehold(userID: String) async throws -> HouseholdAnswers {
        guard let url = URL(string: "\(baseURL)/onboarding/household?user_id=\(userID)") else {
            throw URLError(.badURL)
        }
        let (data, response) = try await URLSession.shared.data(from: url)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        struct Wrapper: Codable { let answers: HouseholdAnswers }
        return try JSONDecoder().decode(Wrapper.self, from: data).answers
    }

    private func apiGetChecklist() async throws -> ([ChecklistCategory], ChecklistTabMode) {
        var comps = URLComponents(string: "\(baseURL)/checklist")
        if let uid = userId {
            comps?.queryItems = [URLQueryItem(name: "user_id", value: uid)]
        }
        guard let url = comps?.url else {
            throw URLError(.badURL)
        }
        let (data, _) = try await URLSession.shared.data(from: url)
        let decoded = try JSONDecoder().decode(ChecklistFetchResponse.self, from: data)
        let mode = ChecklistTabMode(rawValue: decoded.mode) ?? .onboarding
        return (decoded.categories, mode)
    }

    private func postHouseholdAnswers(_ answers: HouseholdAnswers) async throws {
        guard let uid = userId, !uid.isEmpty else {
            throw URLError(.userAuthenticationRequired)
        }
        guard let url = URL(string: "\(baseURL)/onboarding/household?user_id=\(uid)") else {
            throw URLError(.badURL)
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(answers)
        let (_, response) = try await URLSession.shared.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 201 else {
            throw URLError(.badServerResponse)
        }
        // Clear local cache so any other ChecklistManager instance (the tab)
        // doesn't load stale onboarding data on next appear.
        UserDefaults.standard.removeObject(forKey: kChecklistKey)
        UserDefaults.standard.removeObject(forKey: kChecklistModeKey)
        try? FileManager.default.removeItem(at: Self.cacheFileURL)

        // After first successful household save, next fetch shows evacuation checklist
        await fetch()
        NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
    }

    private func apiPatchItem(itemID: String, checked: Bool) async throws {
        guard let url = URL(string: "\(baseURL)/checklist/item") else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var payload: [String: Any] = [
            "item_id": itemID,
            "checked": checked,
        ]
        if let uid = userId { payload["user_id"] = uid }
        req.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (_, response) = try await URLSession.shared.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
    }
}
