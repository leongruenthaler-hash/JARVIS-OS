import SwiftUI
import UIKit

struct RootView: View {
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
        TabView {
            NavigationStack { ChatView() }
                .tabItem { Label("Chat", systemImage: "message.fill") }

            NavigationStack { MemoryView() }
                .tabItem { Label("Speicher", systemImage: "brain") }

            NavigationStack { SettingsView() }
                .tabItem { Label("Einstellungen", systemImage: "slider.horizontal.3") }

            NavigationStack { PairingView() }
                .tabItem { Label("Verbindung", systemImage: "network") }
        }
        .tint(JarvisTheme.accent)
        .preferredColorScheme(.dark)
    }
}

#Preview {
    RootView()
}
