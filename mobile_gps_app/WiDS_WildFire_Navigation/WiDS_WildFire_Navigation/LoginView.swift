//
//  LoginView.swift
//  WiDS_WildFire_Navigation
//

import SwiftUI

// Top languages shown inline; full list available in the sheet.
private let _loginTopLanguages: [(code: String, name: String)] = [
    ("en", "English"), ("es", "Español"), ("zh", "中文"),
    ("vi", "Tiếng Việt"), ("tl", "Filipino"), ("ko", "한국어"),
    ("hi", "हिन्दी"), ("ar", "العربية"), ("fr", "Français"),
]

struct LoginView: View {
    @EnvironmentObject var auth: AuthManager
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var translations: TranslationManager
    @State private var email      = ""
    @State private var password   = ""
    @State private var isLoading  = false
    @State private var errorMsg: String? = nil
    @State private var showLangSheet = false

    private let green  = Color(red: 185/255, green: 58/255, blue: 18/255)
    private let gold   = Color(red: 205/255, green: 163/255, blue: 35/255)

    var body: some View {
        NavigationStack {
            ZStack {
                green.ignoresSafeArea()

                VStack(spacing: 24) {
                    Image(systemName: "flame.fill")
                        .font(.system(size: 60))
                        .foregroundColor(gold)

                    Text(translations.t("WiDS Wildfire Navigation"))
                        .font(.title2).bold()
                        .foregroundColor(.white)

                    // Language picker row
                    Button {
                        showLangSheet = true
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "globe")
                            Text(_loginTopLanguages.first(where: { $0.code == settings.language })?.name
                                 ?? settings.language)
                            Image(systemName: "chevron.down")
                                .font(.caption)
                        }
                        .font(.subheadline)
                        .foregroundColor(.white.opacity(0.85))
                        .padding(.horizontal, 14)
                        .padding(.vertical, 7)
                        .background(.white.opacity(0.15))
                        .cornerRadius(20)
                    }
                    .confirmationDialog("Select Language", isPresented: $showLangSheet, titleVisibility: .visible) {
                        ForEach(supportedLanguages, id: \.code) { lang in
                            Button(lang.name) { settings.language = lang.code }
                        }
                        Button("Cancel", role: .cancel) {}
                    }

                    VStack(spacing: 12) {
                        TextField(translations.t("Email"), text: $email)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .padding()
                            .background(Color.white.opacity(0.9))
                            .cornerRadius(10)

                        SecureField(translations.t("Password"), text: $password)
                            .padding()
                            .background(Color.white.opacity(0.9))
                            .cornerRadius(10)
                    }

                    if let msg = errorMsg {
                        Text(msg)
                            .foregroundColor(gold)
                            .font(.footnote)
                            .multilineTextAlignment(.center)
                    }

                    Button {
                        Task { await login() }
                    } label: {
                        if isLoading {
                            ProgressView().tint(.white)
                        } else {
                            Text(translations.t("Log In"))
                                .bold()
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .padding()
                    .background(gold)
                    .foregroundColor(.white)
                    .cornerRadius(10)
                    .disabled(isLoading || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || password.isEmpty)

                    NavigationLink(translations.t("Don't have an account? Register"), destination: RegisterView())
                        .foregroundColor(gold)
                        .font(.footnote)
                }
                .padding(.horizontal, 32)
            }
            .navigationBarHidden(true)
        }
    }

    private func login() async {
        isLoading = true
        errorMsg  = nil
        defer { isLoading = false }
        do {
            try await auth.login(
                email: email.trimmingCharacters(in: .whitespacesAndNewlines),
                password: password
            )
        } catch {
            errorMsg = error.localizedDescription
        }
    }
}
