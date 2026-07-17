import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    /// Independent of `JarvisTheme` (color-only recolor of MainShellView) - this picks
    /// between two structurally different view trees. Set via Settings > Design > "Ansicht".
    @AppStorage("JarvisDashboardLayoutEnabled") private var dashboardLayoutEnabled = false

    var body: some View {
        Group {
            if !appState.onboardingCompleted {
                OnboardingView()
            } else if dashboardLayoutEnabled {
                DashboardView()
            } else {
                MainShellView()
            }
        }
        .frame(minWidth: 1040, minHeight: 600)
        .background {
            rootBackground
        }
    }

    @ViewBuilder
    private var rootBackground: some View {
        if theme.isFuturistic {
            Color.black
        } else {
            Color(nsColor: .windowBackgroundColor)
        }
    }
}
