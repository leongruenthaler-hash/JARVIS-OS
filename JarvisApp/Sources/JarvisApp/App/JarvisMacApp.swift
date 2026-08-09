import SwiftUI
import AppKit
import UserNotifications

@main
struct JarvisMacApp: App {
    @NSApplicationDelegateAdaptor(JarvisAppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()
    @AppStorage("JarvisActiveTheme") private var activeThemeRaw = JarvisTheme.classic.rawValue

    private var activeTheme: JarvisTheme {
        JarvisTheme(rawValue: activeThemeRaw) ?? .classic
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appState)
                .environment(\.jarvisTheme, activeTheme)
                .onAppear {
                    JarvisAppDelegate.activateJarvisWindow()
                    appDelegate.serverController = appState.serverController
                }
                .task {
                    await appState.bootstrap()
                }
        }

        Settings {
            SettingsView()
                .environmentObject(appState)
                .environment(\.jarvisTheme, activeTheme)
                .frame(width: 720, height: 520)
        }
    }
}

final class JarvisAppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    weak var serverController: LocalServerController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        Self.activateJarvisWindow()
        UNUserNotificationCenter.current().delegate = self
    }

    /// Klick auf eine Proactivity-Systembenachrichtigung bringt Jarvis in den
    /// Vordergrund (siehe plans/2026-08-09-jarvis-systembenachrichtigungen.md) - nutzt
    /// dieselbe Aktivierungslogik wie ein normaler App-Start/-Fokuswechsel.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        Self.activateJarvisWindow()
        completionHandler()
    }

    /// Ohne das würde macOS eine Benachrichtigung stillschweigend unterdrücken, solange
    /// die App bereits im Vordergrund ist - genau dann soll sie aber trotzdem erscheinen
    /// (die App im Vordergrund heißt nicht, dass der Chat-Verlauf gerade sichtbar ist).
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        Self.activateJarvisWindow()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        serverController?.shutdownForAppQuit()
        return .terminateNow
    }

    static func activateJarvisWindow() {
        DispatchQueue.main.async {
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
            for window in NSApp.windows where window.isVisible {
                window.acceptsMouseMovedEvents = true
                window.makeKeyAndOrderFront(nil)
                break
            }
        }
    }
}
