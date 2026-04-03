//
//  RegisterView.swift
//  WiDS_WildFire_Navigation
//

import SwiftUI

struct RegisterView: View {
    @EnvironmentObject var auth: AuthManager
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var translations: TranslationManager
    @Environment(\.dismiss) private var dismiss
    @State private var showLangSheet = false
    @State private var name      = ""
    @State private var email     = ""
    @State private var address   = ""
    @State private var password  = ""
    @State private var confirm   = ""
    @State private var isLoading = false
    @State private var errorMsg: String? = nil

    private let green = Color(red: 185/255, green: 58/255, blue: 18/255)
    private let gold  = Color(red: 205/255, green: 163/255, blue: 35/255)

    private var passwordsMatch: Bool { password == confirm }
    private var canSubmit: Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && !password.isEmpty
        && passwordsMatch
        && !isLoading
    }

    var body: some View {
        ZStack {
            green.ignoresSafeArea()

            VStack(spacing: 24) {
                Image(systemName: "person.badge.plus")
                    .font(.system(size: 60))
                    .foregroundColor(gold)

                Text(translations.t("Create Account"))
                    .font(.title2).bold()
                    .foregroundColor(.white)

                // Language picker row
                Button {
                    showLangSheet = true
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "globe")
                        Text(supportedLanguages.first(where: { $0.code == settings.language })?.name
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
                    TextField(translations.t("Name"), text: $name)
                        .textInputAutocapitalization(.words)
                        .padding()
                        .background(Color.white.opacity(0.9))
                        .cornerRadius(10)

                    TextField(translations.t("Email"), text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding()
                        .background(Color.white.opacity(0.9))
                        .cornerRadius(10)

                    TextField(translations.t("Address (optional)"), text: $address, axis: .vertical)
                        .lineLimit(2...4)
                        .padding()
                        .background(Color.white.opacity(0.9))
                        .cornerRadius(10)

                    SecureField(translations.t("Password"), text: $password)
                        .padding()
                        .background(Color.white.opacity(0.9))
                        .cornerRadius(10)

                    SecureField(translations.t("Confirm Password"), text: $confirm)
                        .padding()
                        .background(Color.white.opacity(0.9))
                        .cornerRadius(10)

                    if !confirm.isEmpty && !passwordsMatch {
                        Text(translations.t("Passwords do not match"))
                            .foregroundColor(gold)
                            .font(.footnote)
                    }
                }

                if let msg = errorMsg {
                    Text(msg)
                        .foregroundColor(gold)
                        .font(.footnote)
                        .multilineTextAlignment(.center)
                }

                Button {
                    Task { await register() }
                } label: {
                    if isLoading {
                        ProgressView().tint(.white)
                    } else {
                        Text(translations.t("Register"))
                            .bold()
                            .frame(maxWidth: .infinity)
                    }
                }
                .padding()
                .background(canSubmit ? gold : Color.gray)
                .foregroundColor(.white)
                .cornerRadius(10)
                .disabled(!canSubmit)

                Button(translations.t("Already have an account? Log in")) { dismiss() }
                    .foregroundColor(gold)
                    .font(.footnote)
            }
            .padding(.horizontal, 32)
        }
        .navigationBarHidden(true)
    }

    private func register() async {
        isLoading = true
        errorMsg  = nil
        defer { isLoading = false }
        do {
            let trimmedAddress = address.trimmingCharacters(in: .whitespacesAndNewlines)
            try await auth.register(
                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                email: email.trimmingCharacters(in: .whitespacesAndNewlines),
                password: password,
                address: trimmedAddress.isEmpty ? nil : trimmedAddress
            )
        } catch {
            errorMsg = error.localizedDescription
        }
    }
}
