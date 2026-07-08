import SwiftUI
import AppKit

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

final class JarvisAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        Self.activateJarvisWindow()
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        Self.activateJarvisWindow()
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
