//
//  OnboardingManager.swift
//  WiDS_WildFire_Navigation
//

import Foundation
import Combine

// MARK: - Models

/// Mirrors HouseholdAnswers in onboarding_api.py — keep in sync.
/// `nil` means not yet answered (server JSON null); `true` / `false` are explicit.
struct HouseholdAnswers: Codable {
    var ownsHome:     Bool? = nil
    var hasCar:       Bool? = nil
    var hasGarage:    Bool? = nil
    var hasDriveway:  Bool? = nil
    var hasPool:      Bool? = nil
    var hasWell:      Bool? = nil
    var hasGenerator: Bool? = nil
    var hasPets:      Bool? = nil
    var hasLivestock: Bool? = nil
    var hasChildren:  Bool? = nil
    var hasSeniors:   Bool? = nil
    var hasDisabled:  Bool? = nil

    // Snake_case keys to match the FastAPI schema exactly
    enum CodingKeys: String, CodingKey {
        case ownsHome     = "owns_home"
        case hasCar       = "has_car"
        case hasGarage    = "has_garage"
        case hasDriveway  = "has_driveway"
        case hasPool      = "has_pool"
        case hasWell      = "has_well"
        case hasGenerator = "has_generator"
        case hasPets      = "has_pets"
        case hasLivestock = "has_livestock"
        case hasChildren  = "has_children"
        case hasSeniors   = "has_seniors"
        case hasDisabled  = "has_disabled"
    }
}

struct OnboardingStatusResponse: Codable {
    let userId: String
    let completed: Bool

    enum CodingKeys: String, CodingKey {
        case userId    = "user_id"
        case completed
    }
}

// MARK: - Manager

private let kOnboardingKey = "onboarding_answers"

class OnboardingManager: ObservableObject {
    @Published var answers    = HouseholdAnswers()
    @Published var isLoading  = false
    @Published var errorMsg: String? = nil
    /// Set to true once the backend confirms onboarding is complete.
    /// App root view observes this to show/hide the onboarding flow.
    @Published var isCompleted = false

    var settings: SettingsManager?

    init() { loadLocal() }

    // MARK: - Launch check

    /// Call on cold launch. Sets isCompleted so the root view routes correctly.
    func checkStatus(userID: String) async {
        await MainActor.run { isLoading = true }
        do {
            let status = try await apiGetStatus(userID: userID)
            if status.completed {
                // Already onboarded — optionally load saved answers for edit screen
                let saved = try? await apiGetHousehold(userID: userID)
                await MainActor.run {
                    if let saved { answers = saved }
                    isCompleted = true
                    isLoading   = false
                }
            } else {
                await MainActor.run { isCompleted = false; isLoading = false }
            }
        } catch {
            // Network failure — fall back to local cache
            await MainActor.run {
                isLoading = false
                // If we have locally persisted answers, treat as completed offline
                isCompleted = UserDefaults.standard.data(forKey: kOnboardingKey) != nil
            }
        }
    }

    // MARK: - Submit

    /// Called when user taps "Done" on the last onboarding step.
    func submit(userID: String) async {
        await MainActor.run { isLoading = true; errorMsg = nil }
        do {
            try await apiPostHousehold(userID: userID, answers: answers)
            saveLocal()
            await MainActor.run { isCompleted = true; isLoading = false }
        } catch {
            await MainActor.run {
                isLoading = false
                errorMsg  = "Could not save your answers: \(error.localizedDescription)"
            }
        }
    }

    // MARK: - Local persistence

    private func saveLocal() {
        guard let data = try? JSONEncoder().encode(answers) else { return }
        UserDefaults.standard.set(data, forKey: kOnboardingKey)
    }

    private func loadLocal() {
        guard let data   = UserDefaults.standard.data(forKey: kOnboardingKey),
              let saved  = try? JSONDecoder().decode(HouseholdAnswers.self, from: data)
        else { return }
        answers = saved
    }

    // MARK: - API

    private var baseURL: String {
        settings?.baseURL ?? "http://localhost:8000"
    }

    private func apiGetStatus(userID: String) async throws -> OnboardingStatusResponse {
        guard let url = URL(string: "\(baseURL)/onboarding/status?user_id=\(userID)") else {
            throw URLError(.badURL)
        }
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONDecoder().decode(OnboardingStatusResponse.self, from: data)
    }

    private func apiGetHousehold(userID: String) async throws -> HouseholdAnswers {
        guard let url = URL(string: "\(baseURL)/onboarding/household?user_id=\(userID)") else {
            throw URLError(.badURL)
        }
        let (data, _) = try await URLSession.shared.data(from: url)
        // Response is { user_id, answers: {...} } — decode the nested answers
        struct Wrapper: Codable { let answers: HouseholdAnswers }
        return try JSONDecoder().decode(Wrapper.self, from: data).answers
    }

    private func apiPostHousehold(userID: String, answers: HouseholdAnswers) async throws {
        guard let url = URL(string: "\(baseURL)/onboarding/household?user_id=\(userID)") else {
            throw URLError(.badURL)
        }
        var req        = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody   = try JSONEncoder().encode(answers)

        let (_, response) = try await URLSession.shared.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 201 else {
            throw URLError(.badServerResponse)
        }
    }
}