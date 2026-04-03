//
//  ContentView.swift
//  WiDS_WildFire_Navigation
//
//  Created by Diane Woodbridge on 3/5/26.
//

import CoreLocation
import SwiftUI
import MapboxDirections
import MapboxMaps
import MapboxNavigationCore
import MapboxNavigationUIKit

// MARK: - ContentView

struct ContentView: View {
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var tabRouter: MainTabRouter

    var body: some View {
        TabView(selection: Binding(
            get: { tabRouter.selectedTab },
            set: { tabRouter.selectedTab = $0 }
        )) {
            ChatView()
                .tabItem { Image(systemName: "bubble.fill") }
                .tag(0)

            NavigationViewControllerRepresentable()
                .tabItem { Image(systemName: "map.fill") }
                .tag(1)

            ChecklistView()
                .tabItem { Image(systemName: "checklist") }
                .tag(2)

            SettingsView()
                .tabItem { Image(systemName: "gearshape.fill") }
                .tag(3)
        }
        .tint(Color(red: 185/255, green: 58/255, blue: 18/255))
        .onChange(of: tabRouter.selectedTab) { _, tab in
            if tab == 1 { settings.mapTabTapCount += 1 }
        }
    }
}

// MARK: - GeoJSON Parsing

struct DropbyLocation {
    let coordinate: CLLocationCoordinate2D
    let name: String
    let facilityType: String
}

/// Extract LineString coordinates from the first LineString feature in the GeoJSON.
func geojsonURL(filename: String) -> URL? {
    // 1. Caches directory (written by fetchRouteAndPresent)
    let cachesURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    let cachesFile = cachesURL.appendingPathComponent("\(filename).geojson")
    if FileManager.default.fileExists(atPath: cachesFile.path) { return cachesFile }
    // 2. Documents directory
    let docsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    let docsFile = docsURL.appendingPathComponent("\(filename).geojson")
    if FileManager.default.fileExists(atPath: docsFile.path) { return docsFile }
    // 3. App bundle (fallback)
    return Bundle.main.url(forResource: filename, withExtension: "geojson")
}

func loadRouteCoordinates(from filename: String) -> [CLLocationCoordinate2D]? {
    guard let url = geojsonURL(filename: filename) else {
        print("[Map] \(filename).geojson not found in caches, documents, or bundle")
        return nil
    }
    guard let data = try? Data(contentsOf: url) else {
        print("[Map] \(filename).geojson found at \(url.path) but could not be read — deleting")
        try? FileManager.default.removeItem(at: url)
        return nil
    }
    guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        print("[Map] \(filename).geojson is not valid JSON (corrupt?) — deleting: \(url.path)")
        try? FileManager.default.removeItem(at: url)
        return nil
    }

    var rawCoords: [[Double]] = []

    func extractLineStringCoords(from geometry: [String: Any]) {
        guard let geoType = geometry["type"] as? String, geoType == "LineString",
              let coords = geometry["coordinates"] as? [[Double]] else { return }
        rawCoords.append(contentsOf: coords)
    }

    let type = json["type"] as? String
    if type == "FeatureCollection" {
        let features = json["features"] as? [[String: Any]] ?? []
        for feature in features {
            if let geometry = feature["geometry"] as? [String: Any] {
                extractLineStringCoords(from: geometry)
            }
        }
    } else if type == "Feature" {
        if let geometry = json["geometry"] as? [String: Any] {
            extractLineStringCoords(from: geometry)
        }
    }

    guard !rawCoords.isEmpty else {
        print("No LineString coordinates found in \(filename).geojson")
        return nil
    }

    return rawCoords.compactMap { pair in
        guard pair.count >= 2 else { return nil }
        return CLLocationCoordinate2D(latitude: pair[1], longitude: pair[0])
    }
}

/// Extract Point features (drop-by locations) from the GeoJSON.
func loadDropbyLocations(from filename: String) -> [DropbyLocation] {
    guard let url  = geojsonURL(filename: filename),
          let data = try? Data(contentsOf: url),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else { return [] }

    let features = json["features"] as? [[String: Any]] ?? []
    var locations: [DropbyLocation] = []

    for feature in features {
        guard let geometry   = feature["geometry"]   as? [String: Any],
              let geoType    = geometry["type"]       as? String, geoType == "Point",
              let coords     = geometry["coordinates"] as? [Double], coords.count >= 2
        else { continue }

        let props        = feature["properties"] as? [String: Any] ?? [:]
        let name         = props["name"]          as? String ?? "Drop-by"
        let facilityType = props["facility_type"] as? String ?? "other"

        locations.append(DropbyLocation(
            coordinate:   CLLocationCoordinate2D(latitude: coords[1], longitude: coords[0]),
            name:         name,
            facilityType: facilityType
        ))
    }

    return locations
}

// MARK: - NavigationViewControllerRepresentable

struct NavigationViewControllerRepresentable: UIViewControllerRepresentable {
    typealias UIViewControllerType = NavigationContainerViewController
    @EnvironmentObject var settings: SettingsManager
    @EnvironmentObject var translations: TranslationManager
    @EnvironmentObject var auth: AuthManager

    func makeUIViewController(context: Context) -> NavigationContainerViewController {
        NavigationContainerViewController(settings: settings, translations: translations, userId: auth.userId)
    }

    func updateUIViewController(_ uiViewController: NavigationContainerViewController, context: Context) {
        uiViewController.handleMapTabTap(tapCount: settings.mapTabTapCount)
        uiViewController.handleSettingsChange(version: settings.sessionVersion)
    }
}

// MARK: - NavigationContainerViewController

final class NavigationContainerViewController: UIViewController {

    private let settings: SettingsManager?
    private var translations: TranslationManager?
    private let userId: String?

    init(settings: SettingsManager? = nil, translations: TranslationManager? = nil, userId: String? = nil) {
        self.settings = settings
        self.translations = translations
        self.userId = userId
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }

    private func t(_ english: String) -> String { translations?.t(english) ?? english }

    private static let usfGreen = UIColor(red: 185/255, green: 58/255, blue: 18/255, alpha: 1)

    private let spinner: UIActivityIndicatorView = {
        let s = UIActivityIndicatorView(style: .large)
        s.color = UIColor(red: 205/255, green: 163/255, blue: 35/255, alpha: 1)
        s.translatesAutoresizingMaskIntoConstraints = false
        return s
    }()

    private let statusLabel: UILabel = {
        let l = UILabel()
        l.text = ""
        l.textColor = .white
        l.font = .systemFont(ofSize: 16, weight: .medium)
        l.textAlignment = .center
        l.translatesAutoresizingMaskIntoConstraints = false
        return l
    }()

    private let errorLabel: UILabel = {
        let l = UILabel()
        l.textColor = UIColor(red: 205/255, green: 163/255, blue: 35/255, alpha: 1)
        l.font = .systemFont(ofSize: 14, weight: .regular)
        l.textAlignment = .center
        l.numberOfLines = 0
        l.isHidden = true
        l.translatesAutoresizingMaskIntoConstraints = false
        return l
    }()

    private var mapboxNavigationProvider: MapboxNavigationProvider?
    private weak var navVC: NavigationViewController?
    private var dropbyAnnotationManager: CircleAnnotationManager?
    private var styleLoadCancelable: Cancelable?
    private var isPaused = false
    private var isCalculating = false   // prevents concurrent MapboxNavigationProvider creation
    private var calculationTask: Task<Void, Never>?   // cancellable handle for the in-flight calc
    private weak var pauseOverlay: UIView?
    private weak var pauseButton: UIButton?
    private var lastHandledTapCount = 0
    private var lastHandledSettingsVersion = 0
    private var settingsDebounceWork: DispatchWorkItem?
    private var needsRouteRegeneration = false

    // MARK: - HWP Overlay
    private weak var hwpDangerButton: UIButton?
    private weak var hwpLegendView: UIView?
    private var hwpEnabled = false
    private var hwpLegend: [[String: String]] = []   // [{min,max,color,label}]
    private var hwpGeoJSON: [String: Any]? = nil     // cached on map tab hit

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = Self.usfGreen
        [spinner, statusLabel, errorLabel].forEach { view.addSubview($0) }

        NSLayoutConstraint.activate([
            spinner.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -24),
            statusLabel.topAnchor.constraint(equalTo: spinner.bottomAnchor, constant: 16),
            statusLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            statusLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            errorLabel.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 12),
            errorLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            errorLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24)
        ])

        statusLabel.text = t("Calculating evacuation route\u{2026}")
        // Do not auto-start navigation on load — only calculate when the user taps the Map tab.
        showWaitingForRoute()
    }

    private func showWaitingForRoute() {
        spinner.stopAnimating()
        statusLabel.text = t("Tap the Map tab to fetch your evacuation route.")
        statusLabel.isHidden = false
    }

    // MARK: - Route Refresh (called when user taps the Map tab)

    func handleMapTabTap(tapCount: Int) {
        guard tapCount > lastHandledTapCount else { return }
        lastHandledTapCount = tapCount

        // Pre-fetch HWP data in background so danger button overlay is instant
        prefetchHWP()

        // Navigation already running or paused — nothing to do on re-tap
        guard navVC == nil && !isPaused else { return }

        // Settings changed since last route — cancel any pending debounce and re-fetch now.
        if needsRouteRegeneration {
            needsRouteRegeneration = false
            settingsDebounceWork?.cancel()
            settingsDebounceWork = nil
            fetchRouteAndPresent()
            return
        }

        let cachesURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        let cachedFile = cachesURL.appendingPathComponent("route.geojson")
        let attrs = try? FileManager.default.attributesOfItem(atPath: cachedFile.path)
        let modDate = attrs?[.modificationDate] as? Date
        let isStale = modDate.map { Date().timeIntervalSince($0) > 5 * 60 } ?? true

        if !isStale {
            // Route is fresh (< 5 min old) — use it directly
            calculateAndPresent()
        } else {
            // Missing or stale — fetch a new route from the server
            if modDate != nil { print("[Map] route.geojson is stale — re-fetching") }
            fetchRouteAndPresent()
        }
    }

    func newRoute() {
        fetchRouteAndPresent()
    }

    func handleSettingsChange(version: Int) {
        guard version > lastHandledSettingsVersion else { return }
        lastHandledSettingsVersion = version

        // Flag that the next map tab tap must re-fetch, and delete cached geojson.
        needsRouteRegeneration = true
        hwpGeoJSON = nil   // stale — will be re-fetched on next map tab tap
        let cachesURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        try? FileManager.default.removeItem(at: cachesURL.appendingPathComponent("route.geojson"))

        // If the map is already visible, debounce and re-fetch (rapid setting keystrokes cancel previous work).
        settingsDebounceWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.navVC != nil || self.isPaused else { return }
            self.fetchRouteAndPresent()
        }
        settingsDebounceWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8, execute: work)
    }

    private func fetchRouteAndPresent() {
        settingsDebounceWork?.cancel()
        settingsDebounceWork = nil
        guard let settings else {
            calculateAndPresent()
            return
        }

        let loc = (lat: settings.lat, lon: settings.lon)
        let ts  = settings.timestampString
        let base = settings.baseURL

        var comps = URLComponents(string: "\(base)/route/generate")
        var queryItems = [
            URLQueryItem(name: "lat",              value: String(loc.lat)),
            URLQueryItem(name: "lon",              value: String(loc.lon)),
            URLQueryItem(name: "timestamp",        value: ts),
            URLQueryItem(name: "distance",         value: String(settings.distance)),
            URLQueryItem(name: "hwp_threshold",    value: String(settings.hwpThreshold)),
            URLQueryItem(name: "hwp_max_fraction", value: String(settings.hwpMaxFraction)),
            URLQueryItem(name: "max_candidates",   value: String(settings.maxCandidates)),
            URLQueryItem(name: "language",         value: settings.language),
        ]
        if let uid = userId {
            queryItems.append(URLQueryItem(name: "user_id", value: uid))
        }
        if !settings.requireDropBy {
            queryItems.append(URLQueryItem(name: "dropby_type", value: "none"))
        }
        comps?.queryItems = queryItems
        guard let url = comps?.url else { calculateAndPresent(); return }

        // Cancel any in-progress Mapbox route calculation before fetching new data.
        // stopNavigation() returns early when navVC is nil, so explicitly clear the
        // provider and flag here to prevent a second instantiation crash.
        calculationTask?.cancel()
        calculationTask = nil
        mapboxNavigationProvider = nil
        isCalculating = false
        stopNavigation(thenRecalculate: false)   // tear down navVC if one exists
        statusLabel.text = t("Fetching evacuation route\u{2026}")
        statusLabel.isHidden = false
        spinner.startAnimating()

        Task {
            do {
                var req = URLRequest(url: url, timeoutInterval: 180)
                req.httpMethod = "GET"
                let (data, response) = try await URLSession.shared.data(for: req)

                if let http = response as? HTTPURLResponse, http.statusCode == 200,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {

                    if let geojsonString = json["geojson"] as? String {
                        let geojsonData = Data(geojsonString.utf8)
                        let folder = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                        let fileURL = folder.appendingPathComponent("route.geojson")
                        do {
                            try geojsonData.write(to: fileURL)
                            print("[Map] route.geojson saved successfully at: \(fileURL.path)")
                        } catch {
                            print("[Map] Write failed: \(error.localizedDescription)")
                        }

                    } else if (json["status"] as? String) == "no_routes" {
                        let n = json["max_candidates"] as? Int ?? 0
                        await MainActor.run {
                            showNoRoute(maxCandidates: n)
                        }
                        return
                    } else {
                        print("[Map] /route/generate returned unexpected response")
                    }
                }
            } catch {
                print("[Map] Route fetch failed: \(error) — using existing file")
                await MainActor.run {
                    if geojsonURL(filename: "route") != nil {
                        calculateAndPresent()
                    } else {
                        showError("Could not reach server at \(base).\nCheck the URL in Settings.")
                    }
                }
                return
            }
            await MainActor.run { calculateAndPresent() }
        }
    }

    // MARK: - Route Calculation

    private func calculateAndPresent() {
        guard !isCalculating else {
            print("[Map] calculateAndPresent already in progress — skipping duplicate call")
            return
        }
        guard mapboxNavigationProvider == nil else {
            print("[Map] calculateAndPresent: provider already exists — skipping to avoid two nav cores")
            return
        }
        guard let coordinates = loadRouteCoordinates(from: "route"),
              coordinates.count >= 2 else {
            showError("Could not load route.geojson from app bundle yet.")
            return
        }
        isCalculating = true

        print("Route: \(coordinates.count) pts  origin=\(coordinates.first!)  dest=\(coordinates.last!)")

        // Sample 25 evenly-spaced waypoints so Mapbox follows the GeoJSON path.
        // Intermediate waypoints get separatesLegs=false → single continuous leg.
        let sampled = sampleCoordinates(from: coordinates, maxTotal: 25)
        let waypoints: [Waypoint] = sampled.enumerated().map { index, coord in
            var wp = Waypoint(coordinate: coord)
            if index != 0 && index != sampled.count - 1 { wp.separatesLegs = false }
            return wp
        }

        // Pin the simulation to the route's first coordinate so it always starts at the origin,
        // even if a previous simulation run advanced the position before being torn down.
        let origin = CLLocation(latitude: coordinates.first!.latitude, longitude: coordinates.first!.longitude)
        let provider = MapboxNavigationProvider(coreConfig: .init(locationSource: .simulation(initialLocation: origin)))
        mapboxNavigationProvider = provider
        let mapboxNavigation = provider.mapboxNavigation

        // Always read language from settings at calculation time so fresh-cache
        // and resume paths reflect the current language, not a stale cached value.
        let activeLang = settings?.language ?? "en"
        let locale = Locale(identifier: activeLang)
        let routeOptions = NavigationRouteOptions(waypoints: waypoints, profileIdentifier: .automobileAvoidingTraffic)
        routeOptions.locale = locale
        routeOptions.includesSpokenInstructions = true
        routeOptions.includesVisualInstructions = true

        let request = mapboxNavigation.routingProvider()
            .calculateRoutes(options: routeOptions)

        let task = Task { @MainActor in
            defer { isCalculating = false }
            switch await request.result {
            case .failure(let error):
                print("Route failed: \(error.localizedDescription)")
                showError("Route calculation failed:\n\(error.localizedDescription)")

            case .success(let routes):
                let navOptions = NavigationOptions(
                    mapboxNavigation: mapboxNavigation,
                    voiceController: provider.routeVoiceController,
                    eventsManager: provider.eventsManager()
                )
                let vc = NavigationViewController(navigationRoutes: routes,
                                                  navigationOptions: navOptions)
                vc.routeLineTracksTraversal = true
                vc.delegate = self
                navVC = vc

                spinner.stopAnimating()
                statusLabel.isHidden = true

                // Embed as a child so the tab bar stays visible.
                addChild(vc)
                vc.view.frame = view.bounds
                vc.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
                view.addSubview(vc.view)
                vc.didMove(toParent: self)

                // Add stop/route/danger buttons over the nav view
                addStopButton(to: vc.view)

                configureAfterPresentation(for: vc)
            }
        }
        calculationTask = task
    }

    // MARK: - Post-presentation setup

    private func configureAfterPresentation(for vc: NavigationViewController) {
        guard let mapView = vc.navigationMapView?.mapView else {
            print("⚠️ mapView not available yet")
            return
        }

        var opts = mapView.gestures.options
        opts.pinchZoomEnabled = true
        mapView.gestures.options = opts

        // Defer layer setup until the style is fully loaded —
        // addSource/addLayer/PointAnnotationManager fail silently if called too early.
        if mapView.mapboxMap.isStyleLoaded {
            addHazardPolygons(to: mapView)
            addDropbyAnnotations(to: mapView)
        } else {
            styleLoadCancelable = mapView.mapboxMap.onStyleLoaded.observeNext { [weak self, weak mapView] _ in
                guard let mapView else { return }
                self?.addHazardPolygons(to: mapView)
                self?.addDropbyAnnotations(to: mapView)
            }
        }
    }

    private func addHazardPolygons(to mapView: MapView) {
        guard let url = geojsonURL(filename: "route") else {
            print("⚠️ route.geojson not found for hazard polygons")
            return
        }

        var source = GeoJSONSource(id: "hazard-source")
        source.data = .url(url)

        var fillLayer = FillLayer(id: "hazard-fill", source: "hazard-source")
        fillLayer.filter = Exp(.eq) { Exp(.geometryType); "Polygon" }
        fillLayer.fillColor = .constant(StyleColor(UIColor(red: 0.8, green: 0.1, blue: 0.1, alpha: 1)))
        fillLayer.fillOpacity = .constant(0.35)

        var outlineLayer = LineLayer(id: "hazard-outline", source: "hazard-source")
        outlineLayer.filter = Exp(.eq) { Exp(.geometryType); "Polygon" }
        outlineLayer.lineColor = .constant(StyleColor(UIColor(red: 0.8, green: 0.1, blue: 0.1, alpha: 1)))
        outlineLayer.lineWidth = .constant(2)

        do {
            try mapView.mapboxMap.addSource(source)
            try mapView.mapboxMap.addLayer(fillLayer)
            try mapView.mapboxMap.addLayer(outlineLayer)
            print("🔴 Hazard polygon layers added")
        } catch {
            print("⚠️ Hazard polygon layers failed: \(error)")
        }
    }

    private func addDropbyAnnotations(to mapView: MapView) {
        let locations = loadDropbyLocations(from: "route")
        guard !locations.isEmpty else {
            print("📍 No drop-by locations found in route.geojson")
            return
        }

        let manager = mapView.annotations.makeCircleAnnotationManager()
        dropbyAnnotationManager = manager

        manager.annotations = locations.enumerated().map { index, loc in
            var circle = CircleAnnotation(centerCoordinate: loc.coordinate)
            circle.circleRadius = 7.0
            circle.circleColor  = StyleColor(UIColor.systemBlue)
            circle.circleStrokeWidth = 2.0
            circle.circleStrokeColor = StyleColor(.white)
            return circle
        }

        print("📍 Added \(locations.count) red dot(s) for drop-by locations")
    }

    // MARK: - HWP Overlay

    @objc private func hwpDangerTapped() {
        hwpEnabled.toggle()
        hwpDangerButton?.tintColor = hwpEnabled ? .systemYellow : .white

        guard let mapView = navVC?.navigationMapView?.mapView else { return }

        if hwpEnabled {
            if let cached = hwpGeoJSON {
                // Data already prefetched — show immediately
                addHWPLayer(geojson: cached, to: mapView)
                if !hwpLegend.isEmpty { showHWPLegend(on: mapView) }
            } else {
                // Fallback: fetch now if prefetch hadn't completed yet
                prefetchHWP { [weak self] in
                    guard let self, let mapView = self.navVC?.navigationMapView?.mapView else { return }
                    if let cached = self.hwpGeoJSON {
                        self.addHWPLayer(geojson: cached, to: mapView)
                        if !self.hwpLegend.isEmpty { self.showHWPLegend(on: mapView) }
                    } else {
                        self.hwpEnabled = false
                        self.hwpDangerButton?.tintColor = .white
                    }
                }
            }
        } else {
            removeHWPLayer(from: mapView)
            hwpLegendView?.removeFromSuperview()
            hwpLegendView = nil
        }
    }

    /// Called when the map tab is hit — fetches HWP data in the background so
    /// tapping the danger button shows the overlay instantly.
    func prefetchHWP(completion: (() -> Void)? = nil) {
        let base = settings?.baseURL ?? AppConstants.defaultBaseURL
        let ts   = settings?.timestampString ?? ISO8601DateFormatter().string(from: Date())
        let legendIsEmpty = hwpLegend.isEmpty

        Task {
            async let legendFetch: Void = {
                guard legendIsEmpty,
                      let url = URL(string: "\(base)/map/hwp/legend"),
                      let (data, _) = try? await URLSession.shared.data(from: url),
                      let json = try? JSONDecoder().decode([[String: String]].self, from: data)
                else { return }
                await MainActor.run { hwpLegend = json }
            }()

            async let hwpFetch: Void = {
                guard let url = URL(string: "\(base)/map/hwp?timestamp=\(ts)"),
                      let (data, _) = try? await URLSession.shared.data(from: url),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      (json["status"] as? String) != "no_data"
                else { return }
                await MainActor.run { hwpGeoJSON = json }
            }()

            _ = await (legendFetch, hwpFetch)
            await MainActor.run { completion?() }
        }
    }

    private func addHWPLayer(geojson: [String: Any], to mapView: MapView) {
        removeHWPLayer(from: mapView)
        guard let geojsonData = try? JSONSerialization.data(withJSONObject: geojson) else { return }

        let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent("hwp_overlay.geojson")
        guard (try? geojsonData.write(to: tempURL)) != nil else { return }

        var source = GeoJSONSource(id: "hwp-overlay-source")
        source.data = .url(tempURL)

        var fillLayer = FillLayer(id: "hwp-overlay-fill", source: "hwp-overlay-source")
        fillLayer.fillColor = .expression(Exp(.get) { "fill" })
        fillLayer.fillOpacity = .expression(Exp(.get) { "fill-opacity" })

        do {
            try mapView.mapboxMap.addSource(source)
            try mapView.mapboxMap.addLayer(fillLayer)
            print("[HWP] Overlay added")
        } catch {
            print("[HWP] Layer add failed: \(error)")
        }
    }

    private func removeHWPLayer(from mapView: MapView) {
        try? mapView.mapboxMap.removeLayer(withId: "hwp-overlay-fill")
        try? mapView.mapboxMap.removeSource(withId: "hwp-overlay-source")
    }

    private func showHWPLegend(on mapView: MapView) {
        hwpLegendView?.removeFromSuperview()

        let container = UIView()
        container.backgroundColor = UIColor.black.withAlphaComponent(0.65)
        container.layer.cornerRadius = 8
        container.translatesAutoresizingMaskIntoConstraints = false

        let stack = UIStackView()
        stack.axis = .vertical
        stack.spacing = 3
        stack.translatesAutoresizingMaskIntoConstraints = false

        let title = UILabel()
        title.text = "HWP Legend"
        title.font = .systemFont(ofSize: 11, weight: .semibold)
        title.textColor = .white
        stack.addArrangedSubview(title)

        for entry in hwpLegend {
            guard let hex = entry["color"], let label = entry["label"] else { continue }
            let row = UIStackView()
            row.axis = .horizontal
            row.spacing = 6
            row.alignment = .center

            let swatch = UIView()
            swatch.backgroundColor = UIColor(hex: hex)
            swatch.layer.cornerRadius = 3
            swatch.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                swatch.widthAnchor.constraint(equalToConstant: 14),
                swatch.heightAnchor.constraint(equalToConstant: 14),
            ])

            let lbl = UILabel()
            lbl.text = label
            lbl.font = .systemFont(ofSize: 10)
            lbl.textColor = .white

            row.addArrangedSubview(swatch)
            row.addArrangedSubview(lbl)
            stack.addArrangedSubview(row)
        }

        container.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: container.topAnchor, constant: 8),
            stack.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -8),
            stack.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 10),
            stack.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -10),
        ])

        mapView.addSubview(container)
        NSLayoutConstraint.activate([
            container.leadingAnchor.constraint(equalTo: mapView.leadingAnchor, constant: 16),
            container.bottomAnchor.constraint(equalTo: mapView.safeAreaLayoutGuide.bottomAnchor, constant: -16),
        ])
        hwpLegendView = container
    }

    // MARK: - Waypoint Sampling

    private func sampleCoordinates(from coords: [CLLocationCoordinate2D],
                                   maxTotal: Int) -> [CLLocationCoordinate2D] {
        guard coords.count > maxTotal, maxTotal >= 2 else { return coords }
        let step = Double(coords.count - 1) / Double(maxTotal - 1)
        return (0..<maxTotal).map { i in
            coords[min(Int((Double(i) * step).rounded()), coords.count - 1)]
        }
    }

    // MARK: - Pause Button (overlaid on nav view)

    private func addStopButton(to navView: UIView) {
        let pauseBtn = makeIconButton(
            systemName: "pause.fill",
            backgroundColor: UIColor(red: 0.8, green: 0.1, blue: 0.1, alpha: 0.85),
            action: #selector(pauseButtonTapped)
        )
        let newRouteBtn = makeIconButton(
            systemName: "arrow.clockwise",
            backgroundColor: UIColor(red: 0.13, green: 0.47, blue: 0.84, alpha: 0.9),
            action: #selector(newRouteTapped)
        )
        let dangerBtn = makeIconButton(
            systemName: "exclamationmark.triangle.fill",
            backgroundColor: UIColor.black.withAlphaComponent(0.55),
            action: #selector(hwpDangerTapped)
        )

        navView.addSubview(pauseBtn)
        navView.addSubview(newRouteBtn)
        navView.addSubview(dangerBtn)
        NSLayoutConstraint.activate([
            pauseBtn.topAnchor.constraint(equalTo: navView.safeAreaLayoutGuide.topAnchor, constant: 12),
            pauseBtn.trailingAnchor.constraint(equalTo: navView.trailingAnchor, constant: -16),
            newRouteBtn.topAnchor.constraint(equalTo: navView.safeAreaLayoutGuide.topAnchor, constant: 12),
            newRouteBtn.trailingAnchor.constraint(equalTo: pauseBtn.leadingAnchor, constant: -8),
            dangerBtn.topAnchor.constraint(equalTo: navView.safeAreaLayoutGuide.topAnchor, constant: 12),
            dangerBtn.trailingAnchor.constraint(equalTo: newRouteBtn.leadingAnchor, constant: -8),
        ])
        pauseButton = pauseBtn
        hwpDangerButton = dangerBtn
    }

    private func makeIconButton(systemName: String, backgroundColor: UIColor, action: Selector) -> UIButton {
        let config = UIImage.SymbolConfiguration(pointSize: 16, weight: .semibold)
        let image  = UIImage(systemName: systemName, withConfiguration: config)

        let btn = UIButton(type: .system)
        btn.setImage(image, for: .normal)
        btn.tintColor = .white
        btn.backgroundColor = backgroundColor
        btn.layer.cornerRadius = 20
        btn.layer.borderColor = UIColor.white.cgColor
        btn.layer.borderWidth = 1.5
        btn.translatesAutoresizingMaskIntoConstraints = false
        btn.addTarget(self, action: action, for: .touchUpInside)
        NSLayoutConstraint.activate([
            btn.widthAnchor.constraint(equalToConstant: 40),
            btn.heightAnchor.constraint(equalToConstant: 40),
        ])
        return btn
    }

    @objc private func newRouteTapped() { newRoute() }

    @objc private func pauseButtonTapped() {
        if isPaused { resumeNavigation() } else { pauseNavigation() }
    }

    // MARK: - Pause / Resume
    //
    // Mapbox's simulation + voice controller keep running even when the nav view is hidden,
    // so "pause" fully tears down the nav VC (stopping audio) and shows an overlay.
    // "Resume" restarts navigation from the route file, same as a fresh start.

    private func pauseNavigation() {
        guard !isPaused, let vc = navVC else { return }
        isPaused = true

        // Tear down so voice / simulation stop immediately
        navVC = nil
        mapboxNavigationProvider = nil
        vc.willMove(toParent: nil)
        vc.view.removeFromSuperview()
        vc.removeFromParent()

        showPauseOverlay()
    }

    private func showPauseOverlay() {
        let overlay = UIView()
        overlay.backgroundColor = Self.usfGreen
        overlay.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(overlay)
        NSLayoutConstraint.activate([
            overlay.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            overlay.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            overlay.topAnchor.constraint(equalTo: view.topAnchor),
            overlay.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
        pauseOverlay = overlay

        let label = UILabel()
        label.text = t("Navigation Paused")
        label.textColor = .white
        label.font = .systemFont(ofSize: 18, weight: .semibold)
        label.translatesAutoresizingMaskIntoConstraints = false
        overlay.addSubview(label)

        let resumeBtn = makeOverlayButton(title: t("Resume"), systemName: "play.fill",
                                          color: UIColor(red: 0.13, green: 0.47, blue: 0.84, alpha: 1),
                                          selector: #selector(resumeTapped))
        let stopBtn   = makeOverlayButton(title: t("Stop"), systemName: "xmark",
                                          color: UIColor(red: 0.8, green: 0.1, blue: 0.1, alpha: 1),
                                          selector: #selector(stopTapped))
        overlay.addSubview(resumeBtn)
        overlay.addSubview(stopBtn)

        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: overlay.centerYAnchor, constant: -56),
            resumeBtn.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            resumeBtn.topAnchor.constraint(equalTo: label.bottomAnchor, constant: 24),
            resumeBtn.widthAnchor.constraint(equalToConstant: 160),
            stopBtn.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            stopBtn.topAnchor.constraint(equalTo: resumeBtn.bottomAnchor, constant: 12),
            stopBtn.widthAnchor.constraint(equalToConstant: 160)
        ])
    }

    private func resumeNavigation() {
        guard isPaused else { return }
        isPaused = false
        pauseOverlay?.removeFromSuperview()
        pauseOverlay = nil

        statusLabel.text     = t("Resuming navigation\u{2026}")
        statusLabel.isHidden = false
        errorLabel.isHidden  = true
        spinner.startAnimating()
        calculateAndPresent()
    }

    @objc private func resumeTapped() { resumeNavigation() }

    @objc private func stopTapped() {
        isPaused = false
        pauseOverlay?.removeFromSuperview()
        pauseOverlay = nil
        stopNavigation()
        showWaitingForRoute()
    }

    private func makeOverlayButton(title: String, systemName: String,
                                    color: UIColor, selector: Selector) -> UIButton {
        let config = UIImage.SymbolConfiguration(pointSize: 14, weight: .semibold)
        let btn = UIButton(type: .system)
        btn.setTitle("  \(title)", for: .normal)   // leading space creates gap after icon
        btn.setImage(UIImage(systemName: systemName, withConfiguration: config), for: .normal)
        btn.tintColor = .white
        btn.setTitleColor(.white, for: .normal)
        btn.titleLabel?.font = .systemFont(ofSize: 16, weight: .semibold)
        btn.backgroundColor = color
        btn.layer.cornerRadius = 22
        btn.layer.borderColor = UIColor.white.cgColor
        btn.layer.borderWidth = 1.5
        btn.translatesAutoresizingMaskIntoConstraints = false
        btn.heightAnchor.constraint(equalToConstant: 44).isActive = true
        btn.addTarget(self, action: selector, for: .touchUpInside)
        return btn
    }

    // MARK: - Stop Navigation

    // Called when the embedded NavigationViewController dismisses itself (X button).
    override func dismiss(animated flag: Bool, completion: (() -> Void)? = nil) {
        stopNavigation()
        showWaitingForRoute()
        completion?()
    }

    func stopNavigation(thenRecalculate: Bool = false) {
        guard let vc = navVC else { return }   // prevent double-calls
        calculationTask?.cancel()
        calculationTask = nil
        navVC = nil
        mapboxNavigationProvider = nil
        isPaused = false
        isCalculating = false   // allow a fresh calculateAndPresent after stop
        pauseOverlay?.removeFromSuperview()
        pauseOverlay = nil

        vc.willMove(toParent: nil)
        vc.view.removeFromSuperview()
        vc.removeFromParent()

        // Reset HWP overlay state so it can be re-added on next route presentation
        hwpEnabled = false
        hwpDangerButton = nil
        hwpLegendView?.removeFromSuperview()
        hwpLegendView = nil

        view.backgroundColor = Self.usfGreen
        errorLabel.isHidden  = true

        if thenRecalculate {
            statusLabel.text     = t("Recalculating route\u{2026}")
            statusLabel.isHidden = false
            spinner.startAnimating()
            calculateAndPresent()
        }
    }

    // MARK: - Error / No-Route State

    private func showNoRoute(maxCandidates: Int) {
        spinner.stopAnimating()
        statusLabel.text    = "🚨 \(t("No evacuation route found"))"
        statusLabel.isHidden = false
        let detail = maxCandidates > 0
            ? "Searched routes to \(maxCandidates) shelters, but none are reachable.\n\nPlease call 911 immediately."
            : "No reachable shelter found.\n\nPlease call 911 immediately."
        errorLabel.text     = detail
        errorLabel.isHidden = false
    }

    private func showError(_ message: String) {
        DispatchQueue.main.async {
            self.spinner.stopAnimating()
            self.statusLabel.text    = "⚠️ \(self.t("Could not start navigation"))"
            self.errorLabel.text     = message
            self.errorLabel.isHidden = false
        }
    }
}

// MARK: - NavigationViewControllerDelegate

extension NavigationContainerViewController: NavigationViewControllerDelegate {

    func navigationViewControllerDidCancelNavigation(
        _ navigationViewController: NavigationViewController
    ) {
        stopNavigation()
    }

    func navigationViewControllerDidDismissArrivalUI(
        _ navigationViewController: NavigationViewController
    ) {
        stopNavigation()
    }
}

// MARK: - UIColor hex helper

private extension UIColor {
    convenience init(hex: String) {
        let h = hex.trimmingCharacters(in: .init(charactersIn: "#"))
        var rgb: UInt64 = 0
        Scanner(string: h).scanHexInt64(&rgb)
        let r = CGFloat((rgb >> 16) & 0xFF) / 255
        let g = CGFloat((rgb >>  8) & 0xFF) / 255
        let b = CGFloat( rgb        & 0xFF) / 255
        self.init(red: r, green: g, blue: b, alpha: 1)
    }
}

#Preview {
    ContentView()
        .environmentObject(SettingsManager())
        .environmentObject(MainTabRouter())
}
