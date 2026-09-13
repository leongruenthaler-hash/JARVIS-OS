import Foundation

/// Teilt ein Ereignis zwischen JarvisMobileApp (empfaengt die Action-Button-
/// URL) und ChatView (startet daraufhin das Mikrofon) - VoiceManager selbst
/// lebt nur innerhalb von ChatView (@StateObject, nicht app-weit ueber
/// @EnvironmentObject erreichbar), deshalb dieses schmale, app-weite Signal
/// dazwischen (2026-09-13, Nutzerwunsch: "Action Button soll direkt das
/// Mikrofon anschalten").
@MainActor
final class VoiceActivationSignal: ObservableObject {
    @Published var pendingAutoListen = false
}
