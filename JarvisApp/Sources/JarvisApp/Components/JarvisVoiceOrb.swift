import SwiftUI

struct JarvisVoiceOrb: View {
    let state: JarvisVoiceState
    let size: CGFloat
    @Environment(\.jarvisTheme) private var theme
    @State private var animate = false
    @State private var phase = false

    var body: some View {
        ZStack {
            backgroundGlow
            pulseRing(scale: outerScale, opacity: outerOpacity, lineWidth: 2)
            pulseRing(scale: middleScale, opacity: middleOpacity, lineWidth: 1.5)
            pulseRing(scale: innerRingScale, opacity: innerRingOpacity, lineWidth: 1)

            if state == .userSpeaking || state == .jarvisSpeaking || state == .listening || state == .liveTranscribing || state == .transcribing {
                voiceBars
                    .frame(width: size * 0.88, height: size * 0.34)
                    .offset(y: state == .jarvisSpeaking ? -2 : 0)
            }

            Circle()
                .fill(
                    RadialGradient(
                        colors: [coreTint.opacity(0.96), coreTint.opacity(0.42), Color(nsColor: .windowBackgroundColor).opacity(0.16)],
                        center: .center,
                        startRadius: 4,
                        endRadius: size * 0.50
                    )
                )
                .frame(width: coreSize, height: coreSize)
                .shadow(color: coreTint.opacity(shadowOpacity), radius: shadowRadius, x: 0, y: 0)
                .scaleEffect(coreScale)
                .animation(coreAnimation, value: animate)

            Circle()
                .strokeBorder(.white.opacity(0.32), lineWidth: 1)
                .frame(width: coreSize * 0.86, height: coreSize * 0.86)
                .rotationEffect(.degrees(rotationDegrees))
                .animation(rotationAnimation, value: animate)

            if state == .thinking {
                orbitingDots
            }

            Image(systemName: state.symbol)
                .font(.system(size: size * 0.16, weight: .semibold))
                .foregroundStyle(.white.opacity(0.94))
                .symbolEffect(.pulse, options: .repeating, value: animate)
                .scaleEffect(symbolScale)
        }
        .frame(width: size, height: size)
        .contentShape(Circle())
        .onAppear {
            animate = true
            phase = true
        }
        .onChange(of: state) {
            phase.toggle()
        }
        .accessibilityLabel(state.title)
    }

    private var backgroundGlow: some View {
        Circle()
            .fill(
                RadialGradient(
                    colors: [state.tint.opacity(backgroundOpacity), state.tint.opacity(0.08), .clear],
                    center: .center,
                    startRadius: 4,
                    endRadius: size * 0.54
                )
            )
            .frame(width: size * 0.96, height: size * 0.96)
            .blur(radius: 18)
            .scaleEffect(animate ? backgroundScale : 0.96)
            .animation(backgroundAnimation, value: animate)
            .allowsHitTesting(false)
    }

    private var coreSize: CGFloat { size * 0.48 }
    private var animationDuration: Double {
        switch state {
        case .idle: return 2.2
        case .preparingMicrophone: return 1.2
        case .listening: return 1.05
        case .userSpeaking: return 0.62
        case .liveTranscribing: return 0.72
        case .transcribing: return 0.82
        case .thinking: return 1.45
        case .jarvisSpeaking: return 0.50
        case .error: return 0.78
        }
    }
    private var coreScale: CGFloat { animate ? activeCoreScale : 1.0 }
    private var activeCoreScale: CGFloat {
        switch state {
        case .idle: return 1.025
        case .preparingMicrophone: return 1.05
        case .listening: return 1.08
        case .userSpeaking: return 1.12
        case .liveTranscribing: return 1.10
        case .transcribing: return 1.09
        case .thinking: return 1.06
        case .jarvisSpeaking: return 1.16
        case .error: return 1.04
        }
    }
    private var shadowOpacity: Double { state == .idle ? 0.30 : 0.56 }
    private var shadowRadius: CGFloat { state == .idle ? 20 : 30 }
    private var backgroundOpacity: Double {
        switch state {
        case .idle: return 0.14
        case .preparingMicrophone: return 0.20
        case .listening: return 0.28
        case .userSpeaking: return 0.36
        case .liveTranscribing: return 0.30
        case .transcribing: return 0.22
        case .thinking: return 0.30
        case .jarvisSpeaking: return 0.36
        case .error: return 0.18
        }
    }
    private var backgroundScale: CGFloat {
        switch state {
        case .idle: return phase ? 1.00 : 0.98
        case .preparingMicrophone: return phase ? 1.02 : 0.99
        case .listening: return phase ? 1.04 : 1.00
        case .userSpeaking: return phase ? 1.07 : 1.01
        case .liveTranscribing: return phase ? 1.05 : 1.00
        case .transcribing: return phase ? 1.03 : 0.99
        case .thinking: return phase ? 1.05 : 0.99
        case .jarvisSpeaking: return phase ? 1.08 : 1.01
        case .error: return phase ? 1.01 : 0.99
        }
    }
    private var outerScale: CGFloat { animate ? outerRingScale : 0.88 }
    private var middleScale: CGFloat { animate ? middleRingScale : 0.80 }
    private var innerRingScale: CGFloat { animate ? innerRingScaleValue : 0.72 }
    private var outerOpacity: Double { outerRingOpacity }
    private var middleOpacity: Double { middleRingOpacity }
    private var innerRingOpacity: Double { innerRingOpacityValue }
    private var coreTint: Color {
        if theme.isFuturistic {
            switch state {
            case .error: return .red
            case .userSpeaking, .liveTranscribing: return theme.secondaryAccent
            case .jarvisSpeaking: return Color(red: 0.38, green: 0.78, blue: 1.0)
            default: return theme.primaryAccent
            }
        }

        switch state {
        case .idle: return .cyan
        case .preparingMicrophone: return .teal
        case .listening: return .blue
        case .userSpeaking: return .green
        case .liveTranscribing: return .mint
        case .transcribing: return .indigo
        case .thinking: return .purple
        case .jarvisSpeaking: return .orange
        case .error: return .red
        }
    }
    private var outerRingScale: CGFloat {
        switch state {
        case .idle: return phase ? 1.02 : 0.98
        case .preparingMicrophone: return phase ? 1.05 : 0.97
        case .listening: return phase ? 1.08 : 0.99
        case .userSpeaking: return phase ? 1.12 : 1.00
        case .liveTranscribing: return phase ? 1.10 : 0.99
        case .transcribing: return phase ? 1.08 : 0.98
        case .thinking: return phase ? 1.08 : 0.96
        case .jarvisSpeaking: return phase ? 1.14 : 1.00
        case .error: return phase ? 1.04 : 0.97
        }
    }
    private var middleRingScale: CGFloat {
        switch state {
        case .idle: return phase ? 0.98 : 0.92
        case .preparingMicrophone: return phase ? 1.00 : 0.94
        case .listening: return phase ? 1.03 : 0.95
        case .userSpeaking: return phase ? 1.06 : 0.97
        case .liveTranscribing: return phase ? 1.05 : 0.96
        case .transcribing: return phase ? 1.02 : 0.94
        case .thinking: return phase ? 1.08 : 0.94
        case .jarvisSpeaking: return phase ? 1.10 : 0.98
        case .error: return phase ? 0.99 : 0.93
        }
    }
    private var innerRingScaleValue: CGFloat {
        switch state {
        case .idle: return phase ? 0.99 : 0.95
        case .preparingMicrophone: return phase ? 1.01 : 0.96
        case .listening: return phase ? 1.03 : 0.97
        case .userSpeaking: return phase ? 1.06 : 0.99
        case .liveTranscribing: return phase ? 1.04 : 0.98
        case .transcribing: return phase ? 1.03 : 0.97
        case .thinking: return phase ? 1.10 : 0.99
        case .jarvisSpeaking: return phase ? 1.08 : 1.00
        case .error: return phase ? 1.00 : 0.95
        }
    }
    private var outerRingOpacity: Double {
        switch state {
        case .idle: return phase ? 0.10 : 0.05
        case .preparingMicrophone: return phase ? 0.16 : 0.07
        case .listening: return phase ? 0.22 : 0.10
        case .userSpeaking: return phase ? 0.30 : 0.14
        case .liveTranscribing: return phase ? 0.24 : 0.12
        case .transcribing: return phase ? 0.18 : 0.09
        case .thinking: return phase ? 0.22 : 0.12
        case .jarvisSpeaking: return phase ? 0.32 : 0.16
        case .error: return phase ? 0.20 : 0.09
        }
    }
    private var middleRingOpacity: Double {
        switch state {
        case .idle: return phase ? 0.14 : 0.08
        case .preparingMicrophone: return phase ? 0.22 : 0.10
        case .listening: return phase ? 0.28 : 0.14
        case .userSpeaking: return phase ? 0.34 : 0.18
        case .liveTranscribing: return phase ? 0.30 : 0.15
        case .transcribing: return phase ? 0.24 : 0.11
        case .thinking: return phase ? 0.30 : 0.14
        case .jarvisSpeaking: return phase ? 0.36 : 0.20
        case .error: return phase ? 0.22 : 0.11
        }
    }
    private var innerRingOpacityValue: Double {
        switch state {
        case .idle: return phase ? 0.12 : 0.08
        case .preparingMicrophone: return phase ? 0.20 : 0.10
        case .listening: return phase ? 0.30 : 0.14
        case .userSpeaking: return phase ? 0.38 : 0.18
        case .liveTranscribing: return phase ? 0.34 : 0.16
        case .transcribing: return phase ? 0.28 : 0.14
        case .thinking: return phase ? 0.36 : 0.18
        case .jarvisSpeaking: return phase ? 0.42 : 0.22
        case .error: return phase ? 0.22 : 0.10
        }
    }
    private var symbolScale: CGFloat {
        switch state {
        case .idle: return phase ? 1.00 : 0.99
        case .preparingMicrophone: return phase ? 1.02 : 1.00
        case .listening: return phase ? 1.04 : 1.00
        case .userSpeaking: return phase ? 1.06 : 1.01
        case .liveTranscribing: return phase ? 1.05 : 1.00
        case .transcribing: return phase ? 1.03 : 0.99
        case .thinking: return phase ? 1.05 : 0.99
        case .jarvisSpeaking: return phase ? 1.08 : 1.02
        case .error: return phase ? 1.01 : 0.99
        }
    }
    private var rotationDegrees: Double {
        guard state == .thinking else { return phase ? 8 : -8 }
        return phase ? 360 : 0
    }
    private var coreAnimation: Animation {
        switch state {
        case .idle:
            return .easeInOut(duration: animationDuration).repeatForever(autoreverses: true)
        case .preparingMicrophone, .listening:
            return .easeInOut(duration: animationDuration).repeatForever(autoreverses: true)
        case .userSpeaking:
            return .spring(response: 0.36, dampingFraction: 0.72, blendDuration: 0.1).repeatForever(autoreverses: true)
        case .liveTranscribing, .transcribing:
            return .easeInOut(duration: animationDuration).repeatForever(autoreverses: true)
        case .thinking:
            return .linear(duration: animationDuration).repeatForever(autoreverses: false)
        case .jarvisSpeaking:
            return .spring(response: 0.24, dampingFraction: 0.76, blendDuration: 0.04).repeatForever(autoreverses: true)
        case .error:
            return .easeInOut(duration: animationDuration).repeatForever(autoreverses: true)
        }
    }
    private var rotationAnimation: Animation {
        switch state {
        case .thinking:
            return .linear(duration: 1.8).repeatForever(autoreverses: false)
        case .jarvisSpeaking:
            return .easeInOut(duration: 0.85).repeatForever(autoreverses: true)
        default:
            return .easeInOut(duration: 1.15).repeatForever(autoreverses: true)
        }
    }

    private var backgroundAnimation: Animation {
        switch state {
        case .thinking:
            return .linear(duration: 2.0).repeatForever(autoreverses: false)
        case .jarvisSpeaking:
            return .easeInOut(duration: 0.9).repeatForever(autoreverses: true)
        case .userSpeaking:
            return .easeInOut(duration: 0.75).repeatForever(autoreverses: true)
        default:
            return .easeInOut(duration: 1.2).repeatForever(autoreverses: true)
        }
    }

    private func pulseRing(scale: CGFloat, opacity: Double, lineWidth: CGFloat) -> some View {
        Circle()
            .stroke(state.tint.opacity(opacity), lineWidth: lineWidth)
            .frame(width: size * 0.86, height: size * 0.86)
            .scaleEffect(scale)
            .animation(.easeInOut(duration: animationDuration).repeatForever(autoreverses: true), value: animate)
    }

    private var voiceBars: some View {
        HStack(alignment: .center, spacing: 6) {
            ForEach(0..<16, id: \.self) { index in
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(state.tint.opacity(barOpacity))
                    .frame(width: 4, height: barHeight(index))
                    .animation(barAnimation(for: index), value: animate)
            }
        }
    }

    private func barHeight(_ index: Int) -> CGFloat {
        let base = size * 0.08
        let variance = CGFloat((index * 7) % 11) / 11.0
        let multiplier: CGFloat
        switch state {
        case .preparingMicrophone: multiplier = animate ? 0.7 + variance * 0.8 : 0.32
        case .listening: multiplier = animate ? 1.0 + variance : 0.48
        case .userSpeaking: multiplier = animate ? 2.0 + variance * 1.9 : 0.75
        case .liveTranscribing: multiplier = animate ? 1.65 + variance * 1.0 : 0.55
        case .transcribing: multiplier = animate ? 1.4 + variance * 0.8 : 0.48
        case .thinking: multiplier = animate ? 1.0 + variance * 0.6 : 0.45
        case .jarvisSpeaking: multiplier = animate ? 2.4 + variance * 1.6 : 0.88
        case .error: multiplier = animate ? 0.9 + variance * 0.4 : 0.42
        case .idle: multiplier = animate ? 0.75 + variance * 0.35 : 0.28
        }
        return base * multiplier
    }

    private var barOpacity: Double {
        switch state {
        case .idle: return 0.0
        case .preparingMicrophone: return 0.42
        case .listening: return 0.52
        case .userSpeaking: return 0.68
        case .liveTranscribing: return 0.58
        case .transcribing: return 0.44
        case .thinking: return 0.34
        case .jarvisSpeaking: return 0.74
        case .error: return 0.42
        }
    }

    private func barAnimation(for index: Int) -> Animation {
        let base = 0.32 + Double(index % 6) * 0.03
        switch state {
        case .thinking:
            return .easeInOut(duration: base + 0.22).repeatForever(autoreverses: true)
        case .jarvisSpeaking:
            return .easeInOut(duration: base + 0.06).repeatForever(autoreverses: true)
        case .userSpeaking:
            return .spring(response: base + 0.18, dampingFraction: 0.58).repeatForever(autoreverses: true)
        case .listening, .liveTranscribing, .transcribing:
            return .easeInOut(duration: base + 0.14).repeatForever(autoreverses: true)
        default:
            return .easeInOut(duration: base + 0.16).repeatForever(autoreverses: true)
        }
    }

    private var orbitingDots: some View {
        ZStack {
            ForEach(0..<4, id: \.self) { index in
                Circle()
                    .fill(state.tint.opacity(0.9 - Double(index) * 0.14))
                    .frame(width: dotSize, height: dotSize)
                    .offset(x: orbitRadius * orbitX(for: index), y: orbitRadius * orbitY(for: index))
                    .shadow(color: state.tint.opacity(0.28), radius: 8, x: 0, y: 0)
                    .rotationEffect(.degrees(phase ? 360 : 0))
                    .animation(.linear(duration: 4.0 + Double(index) * 0.4).repeatForever(autoreverses: false), value: animate)
            }
        }
        .frame(width: size * 0.62, height: size * 0.62)
    }

    private var orbitRadius: CGFloat { size * 0.17 }
    private var dotSize: CGFloat { size * 0.035 }

    private func orbitX(for index: Int) -> CGFloat {
        switch index {
        case 0: return 1
        case 1: return -1
        case 2: return 0.7
        default: return -0.7
        }
    }

    private func orbitY(for index: Int) -> CGFloat {
        switch index {
        case 0: return -0.2
        case 1: return 0.2
        case 2: return 1
        default: return -1
        }
    }
}
