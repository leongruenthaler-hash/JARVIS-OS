import SwiftUI

/// Duenner, gluehender Regler-Stil aus dem "Signal"-Redesign (2026-08-22) - ersetzt den
/// nativen `Slider` fuer Humor-/Ehrlichkeits-Level in `SettingsView`. Bewusst themenfarbig
/// (`theme.primaryAccent`) statt hart auf Mint verdrahtet, damit er bei jedem Theme
/// automatisch mitfaerbt statt eine Signal-exklusive Komponente zu sein.
struct SignalSlider: View {
    @Binding var value: Int
    var range: ClosedRange<Int> = 0...100
    var onEditingChanged: (Bool) -> Void = { _ in }

    @Environment(\.jarvisTheme) private var theme
    @State private var isDragging = false

    private let trackHeight: CGFloat = 4
    private let thumbDiameter: CGFloat = 16

    var body: some View {
        GeometryReader { geometry in
            let width = max(geometry.size.width, 1)
            let fraction = normalizedFraction
            let thumbX = fraction * width

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(theme.primaryAccent.opacity(theme.isDark ? 0.14 : 0.18))
                    .frame(height: trackHeight)

                Capsule()
                    .fill(theme.primaryAccent)
                    .frame(width: thumbX, height: trackHeight)
                    .shadow(color: theme.primaryAccent.opacity(theme.isDark ? 0.6 : 0.3), radius: 6)

                Circle()
                    .fill(Color.white)
                    .frame(width: thumbDiameter, height: thumbDiameter)
                    .shadow(color: theme.primaryAccent.opacity(theme.isDark ? 0.7 : 0.35), radius: isDragging ? 10 : 6)
                    .offset(x: thumbX - thumbDiameter / 2)
            }
            .frame(maxHeight: .infinity, alignment: .center)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { drag in
                        isDragging = true
                        let clampedX = min(max(drag.location.x, 0), width)
                        updateValue(forFraction: clampedX / width)
                        onEditingChanged(true)
                    }
                    .onEnded { _ in
                        isDragging = false
                        onEditingChanged(false)
                    }
            )
        }
        .frame(height: max(thumbDiameter, trackHeight))
    }

    private var normalizedFraction: CGFloat {
        let span = CGFloat(range.upperBound - range.lowerBound)
        guard span > 0 else { return 0 }
        return CGFloat(value - range.lowerBound) / span
    }

    private func updateValue(forFraction fraction: CGFloat) {
        let span = Double(range.upperBound - range.lowerBound)
        let newValue = Int((Double(fraction) * span).rounded()) + range.lowerBound
        value = min(max(newValue, range.lowerBound), range.upperBound)
    }
}
