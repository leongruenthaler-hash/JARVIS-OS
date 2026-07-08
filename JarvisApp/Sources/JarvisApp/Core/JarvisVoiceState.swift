import SwiftUI

enum JarvisVoiceState: String, Equatable {
    case idle
    case preparingMicrophone
    case listening
    case userSpeaking
    case liveTranscribing
    case transcribing
    case thinking
    case jarvisSpeaking
    case error

    var title: String {
        switch self {
        case .idle: return "Bereit"
        case .preparingMicrophone: return "Mikrofon wird vorbereitet"
        case .listening: return "Ich höre zu"
        case .userSpeaking: return "Sprache erkannt"
        case .liveTranscribing: return "Live-Transkript"
        case .transcribing: return "Ich transkribiere"
        case .thinking: return "Ich denke nach"
        case .jarvisSpeaking: return "Ich antworte"
        case .error: return "Aufmerksamkeit nötig"
        }
    }

    var subtitle: String {
        switch self {
        case .idle: return "Drücke das Mikrofon und sprich mit Jarvis."
        case .preparingMicrophone: return "Ich öffne gerade die Audio-Pipeline."
        case .listening: return "Sag, was Jarvis tun soll."
        case .userSpeaking: return "Ich nehme deine Anfrage auf."
        case .liveTranscribing: return "Ich schreibe mit, während du sprichst."
        case .transcribing: return "Ich wandle deine Sprache in Text um."
        case .thinking: return "Ich verarbeite deine Anfrage lokal."
        case .jarvisSpeaking: return "Jarvis spricht über Edge TTS."
        case .error: return "Etwas hat nicht sauber funktioniert."
        }
    }

    var symbol: String {
        switch self {
        case .idle: return "sparkles"
        case .preparingMicrophone: return "mic.badge.plus"
        case .listening: return "mic.fill"
        case .userSpeaking: return "waveform"
        case .liveTranscribing: return "quote.bubble.fill"
        case .transcribing: return "text.magnifyingglass"
        case .thinking: return "brain.head.profile"
        case .jarvisSpeaking: return "speaker.wave.2.fill"
        case .error: return "exclamationmark.triangle.fill"
        }
    }

    var tint: Color {
        switch self {
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
}
