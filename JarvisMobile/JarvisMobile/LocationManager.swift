import Foundation
import CoreLocation

// Ausserhalb der @MainActor-Klasse, damit die nonisolated CLLocationManagerDelegate-
// Methoden (die vom System auch background/nicht auf dem Main-Actor aufgerufen
// werden koennen) ohne Isolations-Fehler darauf zugreifen koennen.
private let jarvisHomeRegionIdentifier = "jarvis-home-region"
private let jarvisHomeRegionRadiusMeters: CLLocationDistance = 100

/// Erkennt per GPS-Geofence, wenn Leon zu Hause ankommt, und meldet das an
/// den Mac Mini (2026-09-12, Nutzerwunsch "Jarvis soll merken, wann ich nach
/// Hause komme und mich begruessen").
///
/// ZWEISTUFIG (2026-09-13, nach drei erfolglosen Direkt-Tests mit 150m/50m/
/// 10m-Radien): iOS' Region-Monitoring selbst ist fuer sehr kleine Radien
/// (< ~50-100m) grundsaetzlich unzuverlaessig - es nutzt aus Akkugruenden
/// bewusst grobe Zellfunk-/WLAN-Ortung fuer die Grenzueberwachung, nicht
/// Dauer-GPS, und Apple empfiehlt selbst mindestens ~100m Radius. Ein
/// direkter 10-15m-Geofence loeste deshalb nie aus, unabhaengig davon, wie
/// genau der gespeicherte Zuhause-Punkt war.
/// Loesung: ein GROSSER, zuverlaessiger Geofence (100m) dient nur als
/// stromsparender Weck-Ausloeser (funktioniert auch im Hintergrund/bei
/// beendeter App) - danach kurz `startUpdatingLocation()` fuer eine
/// PRAEZISE Nachmessung, bis der Abstand zum Zuhause-Punkt wirklich unter
/// `preciseArrivalRadiusMeters` faellt. Erst dann wird begruesst.
@MainActor
final class LocationManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var authorizationStatus: CLAuthorizationStatus
    @Published var homeSet: Bool
    @Published var lastError: String?
    @Published var isCapturingHome = false
    @Published var isRefiningArrival = false
    /// Genauigkeit (Meter) des tatsaechlich gespeicherten Fixes.
    @Published var homeAccuracyMeters: Double?
    @Published var lastRegionState: String?

    private let manager = CLLocationManager()
    private static let homeLatKey = "JarvisHomeLatitude"
    private static let homeLonKey = "JarvisHomeLongitude"
    private static let homeAccuracyKey = "JarvisHomeAccuracy"
    private static let lastArrivalKey = "JarvisLastArrivalAt"
    /// Weck-Radius fuer das eigentliche Region-Monitoring - bewusst gross
    /// gewaehlt, weil iOS kleinere Radien fuer die Grenzueberwachung nicht
    /// zuverlaessig unterstuetzt (siehe Klassen-Kommentar oben).
    /// Erst UNTER dieser praezisen Distanz (per Nachmessung, nicht per
    /// Region-Monitoring selbst) gilt Leon als "wirklich zu Hause" -
    /// behebt den urspruenglichen Fehlalarm bei 150m ("noch auf der
    /// Strasse").
    private static let preciseArrivalRadiusMeters: CLLocationDistance = 20
    /// Sicherheitsabbruch fuer die Nachmessung, falls Leon die Zone zwar
    /// betreten hat, aber z.B. nur vorbeifaehrt und nie wirklich naeher als
    /// `preciseArrivalRadiusMeters` kommt - sonst wuerde GPS unbegrenzt
    /// weiterlaufen und den Akku leeren.
    private static let arrivalRefinementTimeoutSeconds: TimeInterval = 5 * 60
    /// Ein einzelner CLLocationManager.requestLocation()-Fix kann drinnen
    /// 20-50m daneben liegen. Stattdessen kurz `startUpdatingLocation()`
    /// laufen lassen und den ersten Fix nehmen, der besser als dieser Wert
    /// ist (oder nach `homeCaptureTimeoutSeconds` einfach den bis dahin
    /// besten).
    private static let desiredHomeAccuracyMeters: Double = 20
    private static let homeCaptureTimeoutSeconds: TimeInterval = 20
    // Verhindert Mehrfach-Begruessungen, falls GPS am Rand der Zone
    // schwankt - in UserDefaults statt nur im Speicher, weil iOS die App
    // fuer ein Region-Ereignis auch neu startet.
    private static let cooldownSeconds: TimeInterval = 30 * 60

    private var bestCaptureLocation: CLLocation?
    private var captureTimeoutTask: Task<Void, Never>?
    private var arrivalRefinementTimeoutTask: Task<Void, Never>?

    override init() {
        homeSet = UserDefaults.standard.object(forKey: Self.homeLatKey) != nil
        homeAccuracyMeters = UserDefaults.standard.object(forKey: Self.homeAccuracyKey) as? Double
        authorizationStatus = CLLocationManager().authorizationStatus
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        if homeSet {
            startMonitoringHome()
        }
    }

    func requestAuthorization() {
        manager.requestAlwaysAuthorization()
    }

    /// Speichert die AKTUELLE Position als Zuhause-Mittelpunkt - Leon muss
    /// dafuer tatsaechlich zu Hause sein, wenn er das antippt. Sammelt kurz
    /// mehrere Fixes und nimmt den ersten ausreichend genauen (oder nach
    /// Timeout den besten bisherigen), statt blind den allerersten Fix zu
    /// uebernehmen.
    func setCurrentLocationAsHome() {
        bestCaptureLocation = nil
        isCapturingHome = true
        lastError = nil
        manager.startUpdatingLocation()
        captureTimeoutTask?.cancel()
        captureTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(Self.homeCaptureTimeoutSeconds))
            guard !Task.isCancelled else { return }
            self?.finishCapturingHome()
        }
    }

    private func finishCapturingHome() {
        manager.stopUpdatingLocation()
        isCapturingHome = false
        guard let location = bestCaptureLocation else {
            lastError = "Kein GPS-Fix erhalten - bist du drinnen mit schlechtem Empfang?"
            return
        }
        UserDefaults.standard.set(location.coordinate.latitude, forKey: Self.homeLatKey)
        UserDefaults.standard.set(location.coordinate.longitude, forKey: Self.homeLonKey)
        UserDefaults.standard.set(location.horizontalAccuracy, forKey: Self.homeAccuracyKey)
        homeAccuracyMeters = location.horizontalAccuracy
        homeSet = true
        startMonitoringHome()
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.authorizationStatus = status
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.horizontalAccuracy >= 0 else { return }
        Task { @MainActor in
            if self.isCapturingHome {
                if self.bestCaptureLocation == nil || location.horizontalAccuracy < self.bestCaptureLocation!.horizontalAccuracy {
                    self.bestCaptureLocation = location
                }
                if location.horizontalAccuracy <= Self.desiredHomeAccuracyMeters {
                    self.captureTimeoutTask?.cancel()
                    self.finishCapturingHome()
                }
            } else if self.isRefiningArrival {
                self.handleRefinementUpdate(location)
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            self.lastError = error.localizedDescription
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, monitoringDidFailFor region: CLRegion?, withError error: Error) {
        Task { @MainActor in
            self.lastError = "Geofence-Registrierung fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    private func startMonitoringHome() {
        guard let lat = UserDefaults.standard.object(forKey: Self.homeLatKey) as? Double,
              let lon = UserDefaults.standard.object(forKey: Self.homeLonKey) as? Double else { return }
        guard CLLocationManager.isMonitoringAvailable(for: CLCircularRegion.self) else {
            lastError = "Geofencing auf diesem Geraet nicht verfuegbar."
            return
        }
        let center = CLLocationCoordinate2D(latitude: lat, longitude: lon)
        let region = CLCircularRegion(center: center, radius: jarvisHomeRegionRadiusMeters, identifier: jarvisHomeRegionIdentifier)
        region.notifyOnEntry = true
        region.notifyOnExit = false
        manager.startMonitoring(for: region)
    }

    /// Fuer die Diagnose in den Einstellungen: fragt iOS aktiv, ob das
    /// Geraet gerade als innerhalb/ausserhalb/unbekannt der (grossen)
    /// Weck-Zone gilt.
    func checkRegionState() {
        guard let region = manager.monitoredRegions.first(where: { $0.identifier == jarvisHomeRegionIdentifier }) else {
            lastRegionState = "Keine Zone registriert."
            return
        }
        manager.requestState(for: region)
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didDetermineState state: CLRegionState, for region: CLRegion) {
        guard region.identifier == jarvisHomeRegionIdentifier else { return }
        let text: String
        switch state {
        case .inside: text = "Aktuell INNERHALB der \(Int(jarvisHomeRegionRadiusMeters))m-Weck-Zone."
        case .outside: text = "Aktuell AUSSERHALB der \(Int(jarvisHomeRegionRadiusMeters))m-Weck-Zone."
        case .unknown: text = "Status unbekannt (iOS konnte es nicht bestimmen)."
        @unknown default: text = "Unbekannter Status."
        }
        Task { @MainActor in
            self.lastRegionState = text
        }
    }

    func clearHome() {
        UserDefaults.standard.removeObject(forKey: Self.homeLatKey)
        UserDefaults.standard.removeObject(forKey: Self.homeLonKey)
        UserDefaults.standard.removeObject(forKey: Self.homeAccuracyKey)
        homeSet = false
        homeAccuracyMeters = nil
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
            self.startArrivalRefinement()
        }
    }

    /// Startet die praezise Nachmessung, nachdem die grosse Weck-Zone
    /// betreten wurde - laeuft bis der Abstand zum Zuhause-Punkt unter
    /// `preciseArrivalRadiusMeters` faellt oder der Sicherheits-Timeout
    /// greift.
    private func startArrivalRefinement() {
        guard !isRefiningArrival else { return }
        isRefiningArrival = true
        manager.startUpdatingLocation()
        arrivalRefinementTimeoutTask?.cancel()
        arrivalRefinementTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(Self.arrivalRefinementTimeoutSeconds))
            guard !Task.isCancelled else { return }
            self?.stopArrivalRefinement()
        }
    }

    private func stopArrivalRefinement() {
        guard isRefiningArrival else { return }
        isRefiningArrival = false
        manager.stopUpdatingLocation()
        arrivalRefinementTimeoutTask?.cancel()
    }

    private func handleRefinementUpdate(_ location: CLLocation) {
        guard let lat = UserDefaults.standard.object(forKey: Self.homeLatKey) as? Double,
              let lon = UserDefaults.standard.object(forKey: Self.homeLonKey) as? Double else {
            stopArrivalRefinement()
            return
        }
        let home = CLLocation(latitude: lat, longitude: lon)
        let distance = location.distance(from: home)
        guard distance <= Self.preciseArrivalRadiusMeters else { return }
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: Self.lastArrivalKey)
        stopArrivalRefinement()
        Task { await self.notifyArrival() }
    }

    private func notifyArrival() async {
        guard let baseURL = RemoteSettings.presenceBaseURL, let token = RemoteSettings.presenceToken else { return }
        var request = URLRequest(url: baseURL.appendingPathComponent("/api/presence/arrived"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        _ = try? await URLSession.shared.data(for: request)
    }
}
