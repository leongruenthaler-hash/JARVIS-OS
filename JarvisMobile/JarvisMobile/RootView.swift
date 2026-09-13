import SwiftUI
import UIKit

struct RootView: View {
    @EnvironmentObject private var voiceActivation: VoiceActivationSignal
    @State private var selectedTab = 0

    init() {
        // Matches JarvisApp's forced-dark "Signal" theme so both apps feel
        // like the same product - a light-mode tab bar would otherwise leak
        // through the near-black chat background above it.
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(red: 0.02, green: 0.02, blue: 0.024, alpha: 1)
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack { ChatView() }
                .tabItem { Label("Chat", systemImage: "message.fill") }
                .tag(0)

            NavigationStack { MemoryView() }
                .tabItem { Label("Speicher", systemImage: "brain") }
                .tag(1)

            NavigationStack { HealthView() }
                .tabItem { Label("Gesundheit", systemImage: "heart.fill") }
                .tag(2)

            NavigationStack { SettingsView() }
                .tabItem { Label("Einstellungen", systemImage: "slider.horizontal.3") }
                .tag(3)

            NavigationStack { PairingView() }
                .tabItem { Label("Verbindung", systemImage: "network") }
                .tag(4)
        }
        .tint(JarvisTheme.accent)
        .preferredColorScheme(.dark)
        // Action-Button-URL ("jarvismobile://listen") springt zuerst in den
        // Chat-Tab - ChatView selbst startet dann das Mikrofon, sobald es
        // dadurch sichtbar wird (siehe dortiges onChange).
        .onChange(of: voiceActivation.pendingAutoListen) { _, pending in
            guard pending else { return }
            selectedTab = 0
        }
    }
}

#Preview {
    RootView()
}
