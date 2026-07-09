import Foundation

@MainActor
protocol TTSService {
    func speak(_ text: String) async throws
    func speak(_ text: String, onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?) async throws
    func stop() async
}

@MainActor
final class EdgeTTSService: TTSService {
    private let controller: LocalServerController

    init(controller: LocalServerController) {
        self.controller = controller
    }

    func speak(_ text: String) async throws {
        try await speak(text, onEvent: nil)
    }

    func speak(_ text: String, onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?) async throws {
        try await controller.speakText(text, onEvent: onEvent)
    }

    func stop() async {
        await controller.stopSpeaking()
    }
}
