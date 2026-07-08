import SwiftUI

struct RootView: View {
    @Environment(\.jarvisTheme) private var theme

    var body: some View {
        MainShellView()
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
