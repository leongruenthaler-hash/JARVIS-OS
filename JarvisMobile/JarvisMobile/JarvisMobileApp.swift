import SwiftUI

@main
struct JarvisMobileApp: App {
    /// Eine gemeinsame Instanz fuer ChatView UND MemoryView (2026-09-11) - damit das
    /// Kugel-Aufblitzen in der Speicher-Ansicht dieselbe Live-Verbindung nutzt, die auch
    /// den Text-Status im Chat speist. Siehe GatewayClient.swift und JarvisApp's
    /// gleichnamiges Pendant in JarvisMacApp.swift.
    @StateObject private var gatewayClient = GatewayClient()
    @StateObject private var healthKit = HealthKitManager()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(gatewayClient)
                .environmentObject(healthKit)
                .task {
                    guard RemoteSettings.isPaired else { return }
                    gatewayClient.connect(sessionUser: RemoteSettings.sessionUser)
                }
                .task { await healthKit.sync() }
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase == .active else { return }
            Task { await healthKit.sync() }
        }
    }
}
