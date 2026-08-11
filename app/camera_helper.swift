import AVFoundation
import AppKit
import Foundation

// Minimaler CLI-Helfer: nimmt genau EIN Foto von der eingebauten/Standard-Kamera
// auf und schreibt es als JPEG in den uebergebenen --output-Pfad. Kein
// Dauer-Zugriff, keine Vorschau, kein Speichern in einer Bibliothek - das Bild
// existiert nur so lange, wie camera_client.py es danach fuer die
// Vision-Analyse braucht (siehe plans/2026-08-11-jarvis-kamera-feedback.md).

func writeOutput(_ text: String, outputPath: String?) {
    guard let outputPath = outputPath else {
        print(text)
        return
    }
    try? Data(text.utf8).write(to: URL(fileURLWithPath: outputPath))
}

func authorizationStatusString() -> String {
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized: return "authorized"
    case .denied: return "denied"
    case .restricted: return "restricted"
    case .notDetermined: return "notDetermined"
    @unknown default: return "unknown"
    }
}

final class PhotoCaptureCoordinator: NSObject, AVCapturePhotoCaptureDelegate {
    let destination: URL
    var finished = false
    var errorMessage: String?

    init(destination: URL) {
        self.destination = destination
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        defer { finished = true }
        if let error = error {
            errorMessage = "Kamera-Aufnahme fehlgeschlagen: \(error.localizedDescription)"
            return
        }
        guard let data = photo.fileDataRepresentation() else {
            errorMessage = "Kamera lieferte keine Bilddaten."
            return
        }
        do {
            try data.write(to: destination)
        } catch {
            errorMessage = "Foto konnte nicht geschrieben werden: \(error.localizedDescription)"
        }
    }
}

func capturePhoto(outputPath: String) -> String? {
    let status = AVCaptureDevice.authorizationStatus(for: .video)
    if status == .notDetermined {
        let group = DispatchGroup()
        group.enter()
        AVCaptureDevice.requestAccess(for: .video) { _ in group.leave() }
        group.wait()
    }

    let currentStatus = AVCaptureDevice.authorizationStatus(for: .video)
    guard currentStatus == .authorized else {
        return "Kamera-Zugriff wurde nicht erlaubt. Status: \(authorizationStatusString())."
    }

    guard let device = AVCaptureDevice.default(for: .video) else {
        return "Keine Kamera gefunden."
    }

    let session = AVCaptureSession()
    session.sessionPreset = .photo

    do {
        let input = try AVCaptureDeviceInput(device: device)
        guard session.canAddInput(input) else {
            return "Kamera konnte nicht als Eingabe hinzugefuegt werden."
        }
        session.addInput(input)
    } catch {
        return "Kamera konnte nicht geoeffnet werden: \(error.localizedDescription)"
    }

    let output = AVCapturePhotoOutput()
    guard session.canAddOutput(output) else {
        return "Kamera-Ausgabe konnte nicht hinzugefuegt werden."
    }
    session.addOutput(output)

    session.startRunning()
    // Kurze Anlaufzeit, damit der Sensor sich auf Belichtung/Fokus einpendelt,
    // bevor das eigentliche Foto ausgeloest wird - ohne das ist das erste Bild
    // nach dem Start oft zu dunkel/unscharf. RunLoop.run() statt Thread.sleep():
    // dieses CLI-Tool hat keinen eigenen App-Loop, und AVFoundations interne
    // Session-/Capture-Callbacks werden auf manchen macOS-Versionen erst
    // zugestellt, wenn der Haupt-Run-Loop tatsaechlich laeuft - ein reiner
    // Thread.sleep() blockiert das und die Aufnahme haengt komplett (live
    // beobachtet: der Foto-Callback feuerte nie, fester Timeout nach 10s trotz
    // erteilter Kamera-Berechtigung).
    RunLoop.current.run(until: Date().addingTimeInterval(0.6))

    let settings = AVCapturePhotoSettings()
    let coordinator = PhotoCaptureCoordinator(destination: URL(fileURLWithPath: outputPath))
    output.capturePhoto(with: settings, delegate: coordinator)

    let deadline = Date().addingTimeInterval(10)
    while coordinator.errorMessage == nil, !coordinator.finished, Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    session.stopRunning()

    if !coordinator.finished && coordinator.errorMessage == nil {
        return "Kamera hat zu lange nicht geantwortet."
    }
    return coordinator.errorMessage
}

// --- Einstiegspunkt ------------------------------------------------------

// --output ist immer das Ziel fuer die kurze Text-Rueckmeldung ("ok"/"ERROR:...",
// analog zum bestehenden Photos-Helfer). --photo ist ausschliesslich das Ziel
// fuer die eigentliche Bilddatei bei "capture" - getrennt, damit Text- und
// Bild-Ausgabe nie versehentlich denselben Pfad ueberschreiben.
var arguments = Array(CommandLine.arguments.dropFirst())
var command = arguments.first ?? ""
var outputPath: String?
var photoPath: String?

if let outputIndex = arguments.firstIndex(of: "--output"), outputIndex + 1 < arguments.count {
    outputPath = arguments[outputIndex + 1]
}
if let photoIndex = arguments.firstIndex(of: "--photo"), photoIndex + 1 < arguments.count {
    photoPath = arguments[photoIndex + 1]
}

switch command {
case "status":
    writeOutput(authorizationStatusString(), outputPath: outputPath)
case "capture":
    guard let destination = photoPath else {
        writeOutput("ERROR:--photo fehlt.", outputPath: outputPath)
        exit(1)
    }
    if let error = capturePhoto(outputPath: destination) {
        writeOutput("ERROR:\(error)", outputPath: outputPath)
        exit(1)
    }
    writeOutput("ok", outputPath: outputPath)
default:
    writeOutput("ERROR:Unbekannter Befehl: \(command)", outputPath: outputPath)
    exit(1)
}
