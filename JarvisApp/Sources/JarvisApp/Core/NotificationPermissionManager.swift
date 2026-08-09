import Foundation
import UserNotifications

/// Baustein "Systembenachrichtigungen" (siehe
/// plans/2026-08-09-jarvis-systembenachrichtigungen.md): erste zentrale Stelle für
/// eine System-Berechtigung in diesem Projekt - bisher wurde jede Berechtigung (z.B.
/// Mikrofon in AudioCaptureService.swift) direkt an ihrer Nutzungsstelle angefragt.
/// Fragt bewusst nur EINMAL: wird die Anfrage abgelehnt, respektiert Jarvis das und
/// fragt nicht erneut (siehe Leons ausdrückliche Vorgabe).
@MainActor
final class NotificationPermissionManager {
    static let shared = NotificationPermissionManager()

    private let askedKey = "JarvisNotificationPermissionAsked"
    private let center = UNUserNotificationCenter.current()

    private init() {}

    /// Fragt die Berechtigung genau einmal an (beim ersten tatsächlichen
    /// Proactivity-Ereignis, nicht pauschal beim App-Start) und liefert zurück, ob
    /// Benachrichtigungen aktuell erlaubt sind. Wurde schon einmal gefragt, wird nur
    /// noch der aktuelle Status gelesen, nie erneut nachgefragt.
    func requestAuthorizationIfNeeded() async -> Bool {
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return true
        case .denied:
            return false
        case .notDetermined:
            break
        @unknown default:
            break
        }

        if UserDefaults.standard.bool(forKey: askedKey) {
            // Bereits einmal gefragt (z.B. Status noch nicht vom System zurückgemeldet) -
            // nicht erneut fragen, lieber den aktuellen (verneinenden) Stand nutzen.
            return false
        }
        UserDefaults.standard.set(true, forKey: askedKey)

        return await withCheckedContinuation { continuation in
            center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
                continuation.resume(returning: granted)
            }
        }
    }

    func isAuthorized() async -> Bool {
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return true
        default:
            return false
        }
    }
}
