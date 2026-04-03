//
//  AppConstants.swift
//  WiDS_WildFire_Navigation
//
//  Single source of truth for app-wide default values.
//  Change here and it propagates everywhere.
//

import Foundation

enum AppConstants {
    //static let defaultBaseURL = "http://192.168.0.102:8000"
    //static let defaultBaseURL = "http://localhost:8000"
    static let defaultBaseURL = "https://beacon-api-396652353766.us-west1.run.app"
    
    // Default demo location: Montrose County, CO
    static let defaultLat: Double    =  38.50209
    static let defaultLon: Double    = -107.72317

    // Default demo timestamp: August 21 2025, 4 PM local
    static var defaultTimestamp: Date {
        Calendar.current.date(from: DateComponents(
            year: 2025, month: 8, day: 21, hour: 16
        )) ?? Date()
    }

    // Route parameters
    static let defaultDistance: Double       = 50000
    static let defaultHwpThreshold: Double   = 50
    static let defaultHwpMaxFraction: Double = 0.1
    static let defaultMaxCandidates: Int     = 100
    static let defaultRequireDropBy: Bool    = true
}
