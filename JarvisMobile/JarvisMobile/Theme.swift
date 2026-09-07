import SwiftUI

/// Shared visual language for JarvisMobile - mirrors JarvisApp's (macOS) "Signal"
/// dashboard theme (see JarvisApp/Sources/JarvisApp/Core/JarvisTheme.swift +
/// Views/DashboardView.swift::DashboardPalette) so both apps feel like the same
/// product: near-black background, a single bioluminescent mint accent, glass
/// cards. The Mac app derives its mint from an OKLCH color space helper (lightness
/// 0.78, chroma 0.13); this is a plain-RGB approximation of that same hue rather
/// than porting the OKLCH converter for one color.
enum JarvisTheme {
    static let accent = Color(red: 0.42, green: 0.93, blue: 0.76)
    static let accentBright = Color(red: 0.62, green: 0.97, blue: 0.87)

    static let accentGradient = LinearGradient(
        colors: [accent, accentBright],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    /// #050506 - DashboardPalette.background on macOS.
    static let background = Color(red: 0.02, green: 0.02, blue: 0.024)
    static let backgroundBottom = Color(red: 0.012, green: 0.012, blue: 0.016)

    static let cardFill = Color.white.opacity(0.06)
    static let cardStroke = Color.white.opacity(0.12)
    static let assistantBubbleBackground = Color.white.opacity(0.08)

    static let textSecondary = Color(red: 0.612, green: 0.639, blue: 0.686)
}

/// Same near-black-with-a-glow language as JarvisApp's DashboardBackground.
struct JarvisBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [JarvisTheme.background, JarvisTheme.backgroundBottom],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [JarvisTheme.accent.opacity(0.10), .clear],
                center: .topLeading,
                startRadius: 40,
                endRadius: 560
            )
        }
        .ignoresSafeArea()
    }
}
