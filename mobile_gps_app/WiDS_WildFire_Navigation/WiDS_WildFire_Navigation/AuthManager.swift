//
//  AuthManager.swift
//  WiDS_WildFire_Navigation
//

import Foundation
import Combine
import FirebaseMessaging

private let kBaseURLKey = "base_url"
private let kDefaultURL = AppConstants.defaultBaseURL
private let userIDKey   = "user_id"

private var baseURL: String {
    UserDefaults.standard.string(forKey: kBaseURLKey) ?? kDefaultURL
}

private let kNeedsOnboardingKey = "needs_onboarding"

class AuthManager: ObservableObject {
    @Published var isLoggedIn: Bool = false
    @Published var userId: String? = nil
    /// True only for brand-new registrations — cleared once onboarding is submitted.
    @Published var needsOnboarding: Bool = false
    /// Full-screen onboarding editor from Settings (already onboarded users).
    @Published var presentingOnboardingEditor: Bool = false

    private var pendingFCMToken: String? = nil
    private var currentFCMToken: String? = nil
    private var tokenObserver: NSObjectProtocol? = nil
    private var cancellables = Set<AnyCancellable>()

    init() {
        if let stored = UserDefaults.standard.string(forKey: userIDKey) {
            userId = stored
            isLoggedIn = true
        }
        tokenObserver = NotificationCenter.default.addObserver(
            forName: .fcmTokenRefreshed,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let self, let token = notification.object as? String else { return }
            Task { @MainActor in
                if self.isLoggedIn {
                    await self.registerFCMToken(token)
                } else {
                    self.pendingFCMToken = token
                }
            }
        }
    }

    deinit {
        if let obs = tokenObserver {
            NotificationCenter.default.removeObserver(obs)
        }
    }

    // MARK: - Auth

    /// Registers with name, email, password; optional address stored in Postgres `users.address`.
    func register(name: String, email: String, password: String, address: String? = nil) async throws {
        let id = try await postRegister(name: name, email: email, password: password, address: address)
        await MainActor.run { persist(userId: id, isNewUser: true) }
        if let token = pendingFCMToken { await registerFCMToken(token) }
    }

    /// Signs in with email + password (matches Postgres `users.email`).
    func login(email: String, password: String) async throws {
        let id = try await postLogin(email: email, password: password)
        await MainActor.run { persist(userId: id, isNewUser: false) }
        if let token = pendingFCMToken { await registerFCMToken(token) }
    }

    /// Called by ChecklistView after onboarding is successfully submitted.
    func completeOnboarding() {
        needsOnboarding = false
    }

    func openOnboardingEditor() {
        presentingOnboardingEditor = true
    }

    func closeOnboardingEditor() {
        presentingOnboardingEditor = false
    }

    func logout() {
        UserDefaults.standard.removeObject(forKey: userIDKey)
        userId = nil
        isLoggedIn = false
        needsOnboarding = false
        presentingOnboardingEditor = false
    }

    // MARK: - FCM Token

    func registerFCMToken(_ token: String) async {
        guard let id = userId else {
            print("[FCM] No user_id — skipping token registration")
            return
        }
        let language = UserDefaults.standard.string(forKey: "detected_language")
                       ?? Locale.current.language.languageCode?.identifier
                       ?? "en"
        var components = URLComponents(string: "\(baseURL)/monitor/register_fcm_token")
        components?.queryItems = [
            URLQueryItem(name: "user_id",      value: id),
            URLQueryItem(name: "device_token", value: token),
            URLQueryItem(name: "language",     value: language),
        ]
        guard let url = components?.url else {
            print("[FCM] Failed to build registration URL")
            return
        }
        print("[FCM] Registering token for user \(id): \(token.prefix(20))…")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            print("[FCM] Registration response: \(status)")
            if status == 200 {
                await MainActor.run { currentFCMToken = token }
            }
        } catch {
            print("[FCM] Registration failed: \(error)")
        }
        await MainActor.run { pendingFCMToken = nil }
    }

    /// Observe language changes and keep BigQuery in sync.
    /// Call once from the app root alongside translations.attach(to: settings).
    func attach(to settings: SettingsManager) {
        settings.$language
            .dropFirst()
            .removeDuplicates()
            .sink { [weak self] _ in
                guard let self, self.isLoggedIn,
                      let token = self.currentFCMToken else { return }
                Task { await self.registerFCMToken(token) }
            }
            .store(in: &cancellables)
    }

    // MARK: - Private helpers

    private struct RegisterBody: Encodable {
        let name: String
        let email: String
        let password: String
        let address: String?
    }

    private struct LoginBody: Encodable {
        let email: String
        let password: String
    }

    private func postRegister(name: String, email: String, password: String, address: String?) async throws -> String {
        guard let url = URL(string: "\(baseURL)/auth/register") else {
            throw AuthError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let addr = address?.trimmingCharacters(in: .whitespacesAndNewlines)
        let body = RegisterBody(
            name: name,
            email: email,
            password: password,
            address: (addr?.isEmpty == false) ? addr : nil
        )
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AuthError.networkError }

        if http.statusCode == 409 { throw AuthError.emailTaken }
        if http.statusCode == 401 { throw AuthError.invalidCredentials }
        guard http.statusCode == 200 else { throw AuthError.networkError }

        let decoded = try JSONDecoder().decode([String: String].self, from: data)
        guard let id = decoded["user_id"] else { throw AuthError.networkError }
        return id
    }

    private func postLogin(email: String, password: String) async throws -> String {
        guard let url = URL(string: "\(baseURL)/auth/login") else {
            throw AuthError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(LoginBody(email: email, password: password))

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AuthError.networkError }

        if http.statusCode == 409 { throw AuthError.emailTaken }
        if http.statusCode == 401 { throw AuthError.invalidCredentials }
        guard http.statusCode == 200 else { throw AuthError.networkError }

        let decoded = try JSONDecoder().decode([String: String].self, from: data)
        guard let id = decoded["user_id"] else { throw AuthError.networkError }
        return id
    }

    @MainActor
    private func persist(userId id: String, isNewUser: Bool) {
        UserDefaults.standard.set(id, forKey: userIDKey)
        userId = id
        isLoggedIn = true
        needsOnboarding = isNewUser
    }
}

// MARK: - Errors

enum AuthError: LocalizedError {
    case invalidURL
    case networkError
    case emailTaken
    case invalidCredentials

    var errorDescription: String? {
        switch self {
        case .invalidURL:         return "Invalid server URL."
        case .networkError:       return "Network error. Please try again."
        case .emailTaken:         return "That email is already registered."
        case .invalidCredentials: return "Incorrect email or password."
        }
    }
}
