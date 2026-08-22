import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme
    /// Independent of `JarvisTheme` (color-only recolor of MainShellView) - this picks
    /// between two structurally different view trees. Set via Settings > Design > "Ansicht".
    @AppStorage("JarvisDashboardLayoutEnabled") private var dashboardLayoutEnabled = true

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
        // War frueher nur isFuturistic - liess jedes neue dunkle Theme (z.B. .signal)
        // in den hellen windowBackgroundColor-Zweig fallen. isDark deckt alle
        // dunklen Themes ab (siehe JarvisTheme.isDark).
        if theme.isDark {
            Color.black
        } else {
            Color(nsColor: .windowBackgroundColor)
        }
    }
}
