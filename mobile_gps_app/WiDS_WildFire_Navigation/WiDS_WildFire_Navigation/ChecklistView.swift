//
//  ChecklistView.swift
//  WiDS_WildFire_Navigation
//

import SwiftUI

struct ChecklistView: View {
    /// When true (Settings → update onboarding), loads template + saved household and can dismiss without completing first-time flow.
    var editorMode: Bool = false

    @StateObject private var checklist = ChecklistManager()
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var auth: AuthManager
    @EnvironmentObject var translations: TranslationManager

    private let green = Color(red: 185/255, green: 58/255, blue: 18/255)
    private let gold  = Color(red: 205/255, green: 163/255, blue: 35/255)

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text(checklist.tabMode == .onboarding ? translations.t("Onboarding") : translations.t("Evacuation checklist"))
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
                if checklist.isLoading {
                    ProgressView()
                        .tint(gold)
                } else {
                    Button {
                        Task {
                            if editorMode {
                                await checklist.prepareOnboardingEdit()
                            } else {
                                await checklist.fetch()
                            }
                        }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .foregroundColor(gold)
                    }
                }
            }
            .padding()
            .background(green)

            if checklist.categories.isEmpty && !checklist.isLoading {
                emptyState
            } else {
                List {
                    ForEach($checklist.categories) { $category in
                        Section(header: categoryHeader(category.title)) {
                            ForEach($category.items) { $item in
                                ChecklistRow(item: $item, onToggle: {
                                    checklist.toggle(itemID: item.id, in: category.title)
                                }, isOnboarding: checklist.tabMode == .onboarding)
                            }
                        }
                    }
                }
                .listStyle(.insetGrouped)
            }

            if let err = checklist.errorMsg {
                Text(err)
                    .font(.caption)
                    .foregroundColor(.red)
                    .padding()
            }

            if checklist.tabMode == .onboarding && !checklist.categories.isEmpty {
                Button {
                    Task {
                        let ok = await checklist.submitOnboarding()
                        if editorMode && ok {
                            await MainActor.run { auth.closeOnboardingEditor() }
                        }
                    }
                } label: {
                    HStack {
                        if checklist.isSubmittingOnboarding {
                            ProgressView()
                                .tint(.white)
                        }
                        Text(submitButtonTitle)
                            .fontWeight(.semibold)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                }
                .buttonStyle(.borderedProminent)
                .tint(green)
                .padding(.horizontal)
                .padding(.bottom, 12)
                .disabled(checklist.isSubmittingOnboarding)
            }
        }
        .navigationTitle(editorMode ? translations.t("Update onboarding") : "")
        .navigationBarTitleDisplayMode(editorMode ? .inline : .automatic)
        .toolbar {
            if editorMode {
                ToolbarItem(placement: .cancellationAction) {
                    Button(translations.t("Close")) {
                        auth.closeOnboardingEditor()
                    }
                }
            }
        }
        .task {
            checklist.settings = settings
            checklist.userId = auth.userId
            checklist.isOnboardingEditorSession = editorMode
            if editorMode {
                await checklist.prepareOnboardingEdit()
            } else {
                await checklist.fetch()
            }
        }
        .onChange(of: auth.userId) { _, newId in
            checklist.userId = newId
            Task {
                if editorMode {
                    await checklist.prepareOnboardingEdit()
                } else {
                    await checklist.fetch()
                }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .householdAnswersUpdated)) { _ in
            guard !editorMode else { return }
            Task { await checklist.fetch() }
        }
        .onReceive(settings.$language) { _ in
            guard !editorMode else { return }
            Task { await checklist.fetch() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .onboardingCompleted)) { _ in
            // Onboarding was just submitted — re-fetch to get the evacuation checklist
            guard !editorMode else { return }
            Task { await checklist.fetch() }
        }
    }

    private var submitButtonTitle: String {
        if checklist.isSubmittingOnboarding {
            return translations.t("Submitting...")
        }
        if editorMode {
            return translations.t("Save onboarding answers")
        }
        return translations.t("Submit Onboarding")
    }

    private func categoryHeader(_ title: String) -> some View {
        Text(title)
            .font(.subheadline)
            .fontWeight(.semibold)
            .foregroundColor(green)
            .textCase(nil)
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: "checklist")
                .font(.system(size: 48))
                .foregroundColor(.secondary)
            Text(translations.t("No checklist available"))
                .foregroundColor(.secondary)
            Button(translations.t("Retry")) {
                Task {
                    if editorMode {
                        await checklist.prepareOnboardingEdit()
                    } else {
                        await checklist.fetch()
                    }
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(green)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - ChecklistRow

struct ChecklistRow: View {
    @Binding var item: ChecklistItem
    let onToggle: () -> Void
    var isOnboarding: Bool = false

    private let green = Color(red: 185/255, green: 58/255, blue: 18/255)

    var body: some View {
        Button(action: onToggle) {
            HStack(spacing: 12) {
                if isOnboarding {
                    Image(systemName: item.checked ? "checkmark.square.fill" : "square")
                        .font(.system(size: 22))
                        .foregroundColor(item.checked ? green : .secondary)
                } else {
                    Image(systemName: item.checked ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 22))
                        .foregroundColor(item.checked ? green : .secondary)
                }

                Text(item.title)
                    .fontWeight(isOnboarding && item.checked ? .bold : .regular)
                    .foregroundColor(isOnboarding ? (item.checked ? .primary : .secondary) : (item.checked ? .secondary : .primary))
                    .strikethrough(!isOnboarding && item.checked, color: .secondary)
                    .multilineTextAlignment(.leading)

                Spacer()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
