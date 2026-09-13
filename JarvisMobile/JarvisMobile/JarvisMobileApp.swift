import SwiftUI

@main
struct JarvisMobileApp: App {
    /// Eine gemeinsame Instanz fuer ChatView UND MemoryView (2026-09-11) - damit das
    /// Kugel-Aufblitzen in der Speicher-Ansicht dieselbe Live-Verbindung nutzt, die auch
    /// den Text-Status im Chat speist. Siehe GatewayClient.swift und JarvisApp's
    /// gleichnamiges Pendant in JarvisMacApp.swift.
    @StateObject private var gatewayClient = GatewayClient()
    @StateObject private var healthKit = HealthKitManager()
    @StateObject private var locationManager = LocationManager()
    @StateObject private var voiceActivation = VoiceActivationSignal()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(gatewayClient)
                .environmentObject(healthKit)
                .environmentObject(locationManager)
                .environmentObject(voiceActivation)
                .task {
                    guard RemoteSettings.isPaired else { return }
                    gatewayClient.connect(sessionUser: RemoteSettings.sessionUser)
                }
                .task { await healthKit.sync() }
                .onOpenURL { url in
                    // Vom iPhone-Action-Button per Kurzbefehl "URL öffnen"
                    // ausgeloest ("jarvismobile://listen") - bringt die App
                    // direkt in den Chat und startet sofort das Mikrofon,
                    // ohne dass der Nutzer selbst noch tippen muss
                    // (2026-09-13, Nutzerwunsch).
                    guard url.scheme == "jarvismobile", url.host == "listen" else { return }
                    voiceActivation.pendingAutoListen = true
                }
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase == .active else { return }
            Task { await healthKit.sync() }
        }
    }
}
