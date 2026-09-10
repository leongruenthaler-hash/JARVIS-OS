import Foundation

@MainActor
protocol TTSService {
    func speak(_ text: String) async throws
    func speak(_ text: String, onEvent: (@MainActor (BridgeRuntimeEvent) -> Void)?) async throws
    func stop() async
}
