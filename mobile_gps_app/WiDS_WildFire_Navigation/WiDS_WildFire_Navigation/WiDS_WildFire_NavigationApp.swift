//
//  WiDS_WildFire_NavigationApp.swift
//  WiDS_WildFire_Navigation
//
//  Created by Diane Woodbridge on 3/5/26.
//

import SwiftUI

@main
struct WiDS_WildFire_NavigationApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var auth         = AuthManager()
    @StateObject private var settings     = SettingsManager()
    @StateObject private var translations = TranslationManager()
    @StateObject private var tabRouter    = MainTabRouter()

    var body: some Scene {
        WindowGroup {
            Group {
                if !auth.isLoggedIn {
                    LoginView()
                } else if auth.needsOnboarding {
                    ChecklistView()
                        .onReceive(NotificationCenter.default.publisher(for: .onboardingCompleted)) { _ in
                            auth.completeOnboarding()
                        }
                } else {
                    ContentView()
                        .environmentObject(tabRouter)
                        .fullScreenCover(isPresented: $auth.presentingOnboardingEditor) {
                            NavigationStack {
                                ChecklistView(editorMode: true)
                            }
                        }
                }
            }
            .environmentObject(auth)
            .environmentObject(settings)
            .environmentObject(translations)
            .onAppear {
                translations.attach(to: settings)
                auth.attach(to: settings)
            }
        }
    }
}
