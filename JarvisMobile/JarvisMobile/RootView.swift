import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            NavigationStack { ChatView() }
                .tabItem { Label("Chat", systemImage: "message.fill") }

            NavigationStack { ProactivityView() }
                .tabItem { Label("Hinweise", systemImage: "bell.fill") }

            NavigationStack { PairingView() }
                .tabItem { Label("Verbindung", systemImage: "network") }
        }
    }
}

#Preview {
    RootView()
}
