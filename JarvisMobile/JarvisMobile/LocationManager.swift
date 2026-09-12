import Foundation
import CoreLocation

// Ausserhalb der @MainActor-Klasse, damit die nonisolated CLLocationManagerDelegate-
// Methoden (die vom System auch background/nicht auf dem Main-Actor aufgerufen
// werden koennen) ohne Isolations-Fehler darauf zugreifen koennen.
private let jarvisHomeRegionIdentifier = "jarvis-home-region"

/// Erkennt per GPS-Geofence, wenn Leon zu Hause ankommt, und meldet das an
/// den Mac Mini (2026-09-12, Nutzerwunsch "Jarvis soll merken, wann ich nach
/// Hause komme und mich begruessen"). Region-Monitoring statt staendigem
/// GPS-Tracking - iOS weckt die App zuverlaessig genau beim Betreten des
/// Zuhause-Bereichs, auch wenn die App im Hintergrund/beendet ist, ohne
/// Dauer-Standortabfrage und mit minimalem Akkuverbrauch.
@MainActor
final class LocationManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var authorizationStatus: CLAuthorizationStatus
    @Published var homeSet: Bool
    @Published var lastError: String?

    private let manager = CLLocationManager()
    private static let homeLatKey = "JarvisHomeLatitude"
    private static let homeLonKey = "JarvisHomeLongitude"
    private static let lastArrivalKey = "JarvisLastArrivalAt"
    // 150m loeste laut Leon schon aus, waehrend er noch auf der Strasse war,
    // lange vor der eigentlichen Wohnungstuer (2026-09-12) - 50m ist ein
    // Kompromiss zwischen "wirklich fast da" und genug Toleranz fuer
    // GPS-Ungenauigkeit in der Naehe von Gebaeuden.
    private static let regionRadiusMeters: CLLocationDistance = 50
    // Verhindert Mehrfach-Begruessungen, falls GPS am Rand der Zone
    // schwankt (mehrfaches Ein-/Austreten kurz hintereinander) - in
    // UserDefaults statt nur im Speicher, weil iOS die App fuer ein
    // Region-Ereignis auch neu startet (kein laufender Prozess mehr, der
    // sich an den letzten Zeitpunkt erinnern wuerde).
    private static let cooldownSeconds: TimeInterval = 30 * 60

    override init() {
        homeSet = UserDefaults.standard.object(forKey: Self.homeLatKey) != nil
        authorizationStatus = CLLocationManager().authorizationStatus
        super.init()
        manager.delegate = self
        if homeSet {
            startMonitoringHome()
        }
    }

    func requestAuthorization() {
        manager.requestAlwaysAuthorization()
    }

    /// Speichert die AKTUELLE Position als Zuhause-Mittelpunkt - Leon muss
    /// dafuer tatsaechlich zu Hause sein, wenn er das antippt.
    func setCurrentLocationAsHome() {
        manager.requestLocation()
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.authorizationStatus = status
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        Task { @MainActor in
            UserDefaults.standard.set(location.coordinate.latitude, forKey: Self.homeLatKey)
            UserDefaults.standard.set(location.coordinate.longitude, forKey: Self.homeLonKey)
            self.homeSet = true
            self.startMonitoringHome()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            self.lastError = error.localizedDescription
        }
    }

    private func startMonitoringHome() {
        guard let lat = UserDefaults.standard.object(forKey: Self.homeLatKey) as? Double,
              let lon = UserDefaults.standard.object(forKey: Self.homeLonKey) as? Double else { return }
        let center = CLLocationCoordinate2D(latitude: lat, longitude: lon)
        let region = CLCircularRegion(center: center, radius: Self.regionRadiusMeters, identifier: jarvisHomeRegionIdentifier)
        region.notifyOnEntry = true
        region.notifyOnExit = false
        manager.startMonitoring(for: region)
    }

    func clearHome() {
        UserDefaults.standard.removeObject(forKey: Self.homeLatKey)
        UserDefaults.standard.removeObject(forKey: Self.homeLonKey)
        homeSet = false
        for region in manager.monitoredRegions where region.identifier == jarvisHomeRegionIdentifier {
            manager.stopMonitoring(for: region)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didEnterRegion region: CLRegion) {
        guard region.identifier == jarvisHomeRegionIdentifier else { return }
        Task { @MainActor in
            let lastArrivalMs = UserDefaults.standard.double(forKey: Self.lastArrivalKey)
            let now = Date().timeIntervalSince1970
            guard now - lastArrivalMs > Self.cooldownSeconds else { return }
            UserDefaults.standard.set(now, forKey: Self.lastArrivalKey)
            await self.notifyArrival()
        }
    }

    private func notifyArrival() async {
        guard let baseURL = RemoteSettings.presenceBaseURL, let token = RemoteSettings.presenceToken else { return }
        var request = URLRequest(url: baseURL.appendingPathComponent("/api/presence/arrived"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        _ = try? await URLSession.shared.data(for: request)
    }
}
