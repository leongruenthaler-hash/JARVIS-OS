import SwiftUI

struct RootView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        Group {
            if appState.onboardingCompleted {
                MainShellView()
            } else {
                OnboardingView()
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
