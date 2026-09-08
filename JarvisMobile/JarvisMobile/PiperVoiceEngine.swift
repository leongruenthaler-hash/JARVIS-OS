import Foundation

/// Fully offline German neural voice via sherpa-onnx's Piper/VITS support -
/// runs entirely on-device (no Mac Mini, no Microsoft, no network at all).
/// Replaces the earlier network-dependent attempts (direct Edge-TTS from the
/// app: blocked by Microsoft's bot detection; via a Mac-Mini proxy: kept
/// failing over Tailscale despite real debugging - macOS firewall, buffered
/// logs, etc.) with something that simply can't have a network failure mode,
/// per the user's explicit request 2026-09-08 ("können wir die TTS-Stimme
/// nicht direkt in die App einfügen?").
///
/// Model: Thorsten (medium quality, int8-quantized, ~36 MB bundled under
/// PiperVoice/) - a well-regarded free/open German voice
/// (https://github.com/thorstenMueller/Thorsten-Voice, CC0), converted to
/// ONNX by the sherpa-onnx project. Tried bumping to the "high" quality
/// tier 2026-09-08 (closer to the old Microsoft "Killian" voice the user
/// remembered - Killian itself isn't available as an open Piper model) but
/// that crashed the app on-device every time a reply came back - the high
/// model is significantly larger/more compute-heavy, and Piper's own docs
/// already flag "high" as unsuitable for constrained/embedded/mobile
/// inference. Reverted to medium, which is confirmed working.
/// Text-to-phoneme conversion (the hard part for German) comes bundled via
/// espeak-ng-data, exactly matching how the old Python edge-tts-based
/// backend also depended on a mature external phonemizer rather than
/// reinventing one.
enum PiperVoiceEngine {
    private static let wrapper: SherpaOnnxOfflineTtsWrapper? = {
        // Einzeldateien (.onnx, tokens.txt) landen unabhaengig von der
        // virtuellen Xcode-Gruppenstruktur flach im Bundle-Root - nur
        // espeak-ng-data ist eine ECHTE Ordner-Referenz (blauer Ordner in
        // Xcode) und behaelt deshalb seine Unterstruktur im Bundle.
        guard
            let modelPath = Bundle.main.path(forResource: "de_DE-thorsten-medium", ofType: "onnx"),
            let tokensPath = Bundle.main.path(forResource: "tokens", ofType: "txt"),
            let dataDirURL = Bundle.main.url(forResource: "espeak-ng-data", withExtension: nil)
        else {
            return nil
        }
        let vits = sherpaOnnxOfflineTtsVitsModelConfig(
            model: modelPath,
            lexicon: "",
            tokens: tokensPath,
            dataDir: dataDirURL.path
        )
        let modelConfig = sherpaOnnxOfflineTtsModelConfig(vits: vits)
        var config = sherpaOnnxOfflineTtsConfig(model: modelConfig)
        return SherpaOnnxOfflineTtsWrapper(config: &config)
    }()

    /// Synthesizes `text` on-device and returns WAV bytes ready for
    /// AVAudioPlayer, or nil if the bundled model failed to load (should only
    /// happen if the app bundle is somehow missing the model resources).
    static func synthesize(_ text: String, speed: Float = 1.0) -> Data? {
        guard let wrapper else { return nil }
        let audio = wrapper.generate(text: text, sid: 0, speed: speed)
        guard !audio.samples.isEmpty else { return nil }

        let tempFile = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("jarvis_piper_\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: tempFile) }
        guard audio.save(filename: tempFile.path) == 1 else { return nil }
        return try? Data(contentsOf: tempFile)
    }
}
