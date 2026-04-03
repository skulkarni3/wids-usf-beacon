//
//  MainTabRouter.swift
//  WiDS_WildFire_Navigation
//
//  Shared tab selection so chat (and other screens) can deep-link to Map / Checklist / Settings.
//

import Foundation
import Combine

final class MainTabRouter: ObservableObject {
    /// Matches `ContentView` TabView tags: 0 Chat, 1 Map, 2 Checklist, 3 Settings
    @Published var selectedTab: Int = 0

    enum Tab: Int {
        case chat = 0
        case map = 1
        case checklist = 2
        case settings = 3
    }

    func select(_ tab: Tab) {
        selectedTab = tab.rawValue
    }
}
