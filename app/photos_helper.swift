import AppKit
import CoreGraphics
import Foundation
import Photos
import Vision

struct PhotoRecord: Codable {
    let id: String
    let filename: String
    let mediaType: String
    let createdAt: String
    let modifiedAt: String
    let width: Int
    let height: Int
    let favorite: Bool
    let labels: [String]
    let objects: [String]
    let scenes: [String]
    let texts: [String]
    let people: [String]
}

struct ScanStats: Codable {
    let photosFound: Int
    let videosFound: Int
    let indexEntries: Int
    let durationSeconds: Double
}

struct ScanResult: Codable {
    let stats: ScanStats
    let records: [PhotoRecord]
}

let isoFormatter = ISO8601DateFormatter()
var outputPath: String?
var knownMetadata: [String: String] = [:]
var progressPath: String?

func emitData(_ data: Data) {
    if let outputPath = outputPath {
        try? data.write(to: URL(fileURLWithPath: outputPath))
        return
    }

    FileHandle.standardOutput.write(data)
}

func emit(_ message: String) {
    emitData(Data((message + "\n").utf8))
}

func writeProgress(
    status: String,
    current: Int,
    total: Int,
    label: String,
    photosFound: Int,
    videosFound: Int,
    labelsRecognized: Int,
    startedAt: String,
    finishedAt: String? = nil,
    error: String? = nil
) {
    guard let progressPath = progressPath else { return }
    let percentage = total > 0 ? min(100.0, max(0.0, (Double(current) / Double(total)) * 100.0)) : 0.0
    let payload: [String: Any] = [
        "status": status,
        "currentItem": current,
        "totalItems": total,
        "percentage": percentage,
        "currentLabel": label,
        "startedAt": startedAt,
        "finishedAt": finishedAt as Any,
        "errorMessage": error as Any,
        "stats": [
            "photos_found": photosFound,
            "photos_indexed": current,
            "videos_found": videosFound,
            "labels_recognized": labelsRecognized,
            "current_photo": label
        ]
    ]
    if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted]) {
        try? data.write(to: URL(fileURLWithPath: progressPath))
    }
}

func currentPhotoStatus() -> PHAuthorizationStatus {
    if #available(macOS 11.0, *) {
        return PHPhotoLibrary.authorizationStatus(for: .readWrite)
    }

    return PHPhotoLibrary.authorizationStatus()
}

func statusName(_ status: PHAuthorizationStatus) -> String {
    switch status {
    case .authorized:
        return "authorized"
    case .denied:
        return "denied"
    case .notDetermined:
        return "notDetermined"
    case .restricted:
        return "restricted"
    default:
        if #available(macOS 11.0, *), status == .limited {
            return "limited"
        }
        return "unknown"
    }
}

func statusAllowsAccess(_ status: PHAuthorizationStatus) -> Bool {
    if status == .authorized {
        return true
    }

    if #available(macOS 11.0, *), status == .limited {
        return true
    }

    return false
}

func prepareForPermissionDialog() {
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.activate(ignoringOtherApps: true)
}

func authorizePhotos() -> Bool {
    let currentStatus = currentPhotoStatus()
    if statusAllowsAccess(currentStatus) {
        return true
    }

    if currentStatus != .notDetermined {
        return false
    }

    prepareForPermissionDialog()

    var completed = false
    var granted = false

    if #available(macOS 11.0, *) {
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { newStatus in
            granted = statusAllowsAccess(newStatus)
            completed = true
        }
    } else {
        PHPhotoLibrary.requestAuthorization { newStatus in
            granted = statusAllowsAccess(newStatus)
            completed = true
        }
    }

    let deadline = Date().addingTimeInterval(60)
    while !completed && Date() < deadline {
        _ = RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
    }

    return granted
}

func cgImage(for asset: PHAsset) -> CGImage? {
    // Gleiche isSynchronous=false + DispatchSemaphore-Umstellung wie in
    // exportPreview() - siehe Kommentar dort.
    let imageOptions = PHImageRequestOptions()
    imageOptions.isSynchronous = false
    imageOptions.deliveryMode = .fastFormat
    imageOptions.resizeMode = .fast
    imageOptions.isNetworkAccessAllowed = true

    var resultImage: NSImage?
    let semaphore = DispatchSemaphore(value: 0)
    let targetSize = CGSize(width: 700, height: 700)
    PHImageManager.default().requestImage(
        for: asset,
        targetSize: targetSize,
        contentMode: .aspectFit,
        options: imageOptions
    ) { image, _ in
        resultImage = image
        semaphore.signal()
    }

    if semaphore.wait(timeout: .now() + 45) == .timedOut {
        return nil
    }

    guard let image = resultImage else {
        return nil
    }

    var rect = CGRect(origin: .zero, size: image.size)
    return image.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func filename(for asset: PHAsset) -> String {
    if let resource = PHAssetResource.assetResources(for: asset).first {
        return resource.originalFilename
    }

    return asset.localIdentifier.replacingOccurrences(of: "/", with: "_")
}

func mediaTypeName(_ asset: PHAsset) -> String {
    switch asset.mediaType {
    case .image:
        return "image"
    case .video:
        return "video"
    case .audio:
        return "audio"
    default:
        return "unknown"
    }
}

func modifiedAt(for asset: PHAsset) -> String {
    asset.modificationDate.map { isoFormatter.string(from: $0) } ?? ""
}

func metadataOnlyRecord(asset: PHAsset) -> PhotoRecord {
    let createdAt = asset.creationDate.map { isoFormatter.string(from: $0) } ?? ""
    return PhotoRecord(
        id: asset.localIdentifier,
        filename: filename(for: asset),
        mediaType: mediaTypeName(asset),
        createdAt: createdAt,
        modifiedAt: modifiedAt(for: asset),
        width: asset.pixelWidth,
        height: asset.pixelHeight,
        favorite: asset.isFavorite,
        labels: [],
        objects: [],
        scenes: [],
        texts: [],
        people: []
    )
}

func analyze(asset: PHAsset) -> PhotoRecord {
    var labels: [String] = []
    var objects: [String] = []
    var scenes: [String] = []
    var texts: [String] = []
    var people: [String] = []

    if let image = cgImage(for: asset) {
        let classifyRequest = VNClassifyImageRequest()
        let textRequest = VNRecognizeTextRequest()
        let faceRequest = VNDetectFaceRectanglesRequest()
        textRequest.recognitionLevel = .fast
        textRequest.usesLanguageCorrection = false

        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        try? handler.perform([classifyRequest, textRequest, faceRequest])

        if let observations = classifyRequest.results {
            labels = observations
                .filter { $0.confidence >= 0.08 }
                .prefix(20)
                .map { $0.identifier.lowercased() }
            objects = labels.filter { label in
                label.contains("car") || label.contains("vehicle") || label.contains("cat") ||
                label.contains("dog") || label.contains("person") || label.contains("computer") ||
                label.contains("document") || label.contains("food") || label.contains("text")
            }
            scenes = labels.filter { label in
                label.contains("road") || label.contains("sky") || label.contains("beach") ||
                label.contains("room") || label.contains("building") || label.contains("landscape") ||
                label.contains("structure") || label.contains("window")
            }
        }

        if let observations = textRequest.results {
            texts = observations
                .compactMap { $0.topCandidates(1).first?.string }
                .map { $0.lowercased() }
                .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                .prefix(12)
                .map { String($0) }
        }

        if let observations = faceRequest.results, !observations.isEmpty {
            people = Array(repeating: "person", count: min(observations.count, 10))
        }
    }

    let createdAt = asset.creationDate.map { isoFormatter.string(from: $0) } ?? ""
    let modifiedAt = modifiedAt(for: asset)
    return PhotoRecord(
        id: asset.localIdentifier,
        filename: filename(for: asset),
        mediaType: mediaTypeName(asset),
        createdAt: createdAt,
        modifiedAt: modifiedAt,
        width: asset.pixelWidth,
        height: asset.pixelHeight,
        favorite: asset.isFavorite,
        labels: labels,
        objects: objects,
        scenes: scenes,
        texts: texts,
        people: people
    )
}

func scan(limit: Int) throws {
    let startedAt = Date()
    let startedText = isoFormatter.string(from: startedAt)
    let options = PHFetchOptions()
    options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
    if limit > 0 {
        options.fetchLimit = limit
    }

    let assets = PHAsset.fetchAssets(with: options)
    let allImages = PHAsset.fetchAssets(with: .image, options: nil)
    let allVideos = PHAsset.fetchAssets(with: .video, options: nil)
    var records: [PhotoRecord] = []
    records.reserveCapacity(assets.count)
    var labelsRecognized = 0

    writeProgress(
        status: "scanning",
        current: 0,
        total: assets.count,
        label: "Fotos werden vorbereitet.",
        photosFound: allImages.count,
        videosFound: allVideos.count,
        labelsRecognized: 0,
        startedAt: startedText
    )

    assets.enumerateObjects { asset, index, _ in
        let label = filename(for: asset)
        let currentModifiedAt = modifiedAt(for: asset)
        if !currentModifiedAt.isEmpty, knownMetadata[asset.localIdentifier] == currentModifiedAt {
            records.append(metadataOnlyRecord(asset: asset))
        } else {
            records.append(analyze(asset: asset))
        }
        labelsRecognized += records.last?.labels.count ?? 0
        writeProgress(
            status: "indexing",
            current: index + 1,
            total: assets.count,
            label: label,
            photosFound: allImages.count,
            videosFound: allVideos.count,
            labelsRecognized: labelsRecognized,
            startedAt: startedText
        )
    }

    if let first = records.first {
        FileHandle.standardError.write(Data((
            "Fotoindex-Testbild: \(first.filename)\n" +
            "Labels:\n" +
            first.labels.prefix(12).joined(separator: "\n") +
            "\n"
        ).utf8))
    }

    let duration = Date().timeIntervalSince(startedAt)
    let result = ScanResult(
        stats: ScanStats(
            photosFound: allImages.count,
            videosFound: allVideos.count,
            indexEntries: records.count,
            durationSeconds: duration
        ),
        records: records
    )
    FileHandle.standardError.write(Data((
        "Fotos gefunden: \(allImages.count)\n" +
        "Videos gefunden: \(allVideos.count)\n" +
        "Indexeinträge: \(records.count)\n" +
        String(format: "Indexdauer: %.2fs\n", duration)
    ).utf8))

    writeProgress(
        status: "completed",
        current: records.count,
        total: assets.count,
        label: "Fotoindex fertig.",
        photosFound: allImages.count,
        videosFound: allVideos.count,
        labelsRecognized: labelsRecognized,
        startedAt: startedText,
        finishedAt: isoFormatter.string(from: Date())
    )

    let data = try JSONEncoder().encode(result)
    emitData(data)
}

func exportPreview(assetId: String, destinationPath: String, maxSize: Int) throws {
    let assets = PHAsset.fetchAssets(withLocalIdentifiers: [assetId], options: nil)
    guard let asset = assets.firstObject else {
        fail("Foto nicht gefunden.")
    }

    // isSynchronous = false ist hier bewusst: bei true liefert PHImageManager nur
    // zurueck, wenn das Bild schnell/lokal verfuegbar ist - fuer Fotos, die erst
    // aus iCloud nachgeladen werden muessen (z.B. durch "Fotos optimieren"),
    // kam der synchrone Aufruf trotz isNetworkAccessAllowed=true oft sofort mit
    // nil zurueck statt auf den Download zu warten (live beobachtet: ~71-82%
    // Fehlschlagsquote). Der DispatchSemaphore unten wartet stattdessen wirklich
    // auf den asynchronen Callback, mit eigenem Timeout unterhalb des
    // 60s-Subprozess-Timeouts in photos_client.py::_run_helper().
    let imageOptions = PHImageRequestOptions()
    imageOptions.isSynchronous = false
    imageOptions.deliveryMode = .highQualityFormat
    imageOptions.resizeMode = .fast
    imageOptions.isNetworkAccessAllowed = true

    var resultImage: NSImage?
    var requestError: Error?
    let semaphore = DispatchSemaphore(value: 0)
    let size = max(300, maxSize)
    let targetSize = CGSize(width: size, height: size)
    PHImageManager.default().requestImage(
        for: asset,
        targetSize: targetSize,
        contentMode: .aspectFit,
        options: imageOptions
    ) { image, info in
        requestError = info?[PHImageErrorKey] as? Error
        resultImage = image
        semaphore.signal()
    }

    if semaphore.wait(timeout: .now() + 45) == .timedOut {
        fail("Zeitüberschreitung beim Laden aus iCloud.")
    }

    if let requestError = requestError {
        fail("Foto konnte nicht geladen werden: \(requestError.localizedDescription)")
    }

    guard let image = resultImage else {
        fail("Foto lieferte kein Bild (evtl. nicht mehr vorhanden oder beschädigt).")
    }
    guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) else {
        fail("Foto konnte nicht in ein verarbeitbares Format umgewandelt werden.")
    }

    guard let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.72]) else {
        fail("JPEG-Vorschau konnte nicht erzeugt werden.")
    }

    try jpeg.write(to: URL(fileURLWithPath: destinationPath))
    emit(destinationPath)
}

func findAlbum(named name: String) -> PHAssetCollection? {
    let collections = PHAssetCollection.fetchAssetCollections(with: .album, subtype: .albumRegular, options: nil)
    var found: PHAssetCollection?
    collections.enumerateObjects { collection, _, stop in
        if collection.localizedTitle == name {
            found = collection
            stop.pointee = true
        }
    }
    return found
}

func ensureAlbum(named name: String) throws -> PHAssetCollection? {
    if let existing = findAlbum(named: name) {
        return existing
    }

    try PHPhotoLibrary.shared().performChangesAndWait {
        PHAssetCollectionChangeRequest.creationRequestForAssetCollection(withTitle: name)
    }

    return findAlbum(named: name)
}

func addToAlbum(name: String, ids: [String]) throws {
    guard !ids.isEmpty else {
        emit("0")
        return
    }

    guard let album = try ensureAlbum(named: name) else {
        emit("0")
        return
    }

    let assets = PHAsset.fetchAssets(withLocalIdentifiers: ids, options: nil)
    if assets.count == 0 {
        emit("0")
        return
    }

    try PHPhotoLibrary.shared().performChangesAndWait {
        if let request = PHAssetCollectionChangeRequest(for: album) {
            request.addAssets(assets)
        }
    }

    emit("\(assets.count)")
}

func fail(_ message: String) -> Never {
    emit("ERROR: \(message)")
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

var args = CommandLine.arguments
if let outputIndex = args.firstIndex(of: "--output"), outputIndex + 1 < args.count {
    outputPath = args[outputIndex + 1]
    args.removeSubrange(outputIndex...outputIndex + 1)
}
if let knownIndex = args.firstIndex(of: "--known"), knownIndex + 1 < args.count {
    let knownPath = args[knownIndex + 1]
    if let data = try? Data(contentsOf: URL(fileURLWithPath: knownPath)),
       let decoded = try? JSONDecoder().decode([String: String].self, from: data) {
        knownMetadata = decoded
    }
    args.removeSubrange(knownIndex...knownIndex + 1)
}
if let progressIndex = args.firstIndex(of: "--progress"), progressIndex + 1 < args.count {
    progressPath = args[progressIndex + 1]
    args.removeSubrange(progressIndex...progressIndex + 1)
}

guard args.count >= 2 else {
    fail("Befehl fehlt: status, authorize, scan, album oder export.")
}

if args[1] == "status" {
    emit(statusName(currentPhotoStatus()))
    exit(0)
}

if args[1] == "authorize" {
    if authorizePhotos() {
        emit(statusName(currentPhotoStatus()))
        exit(0)
    }

    fail("Fotos-Zugriff wurde nicht erlaubt. Status: \(statusName(currentPhotoStatus())).")
}

if !authorizePhotos() {
    fail("Fotos-Zugriff wurde nicht erlaubt. Status: \(statusName(currentPhotoStatus())).")
}

do {
    switch args[1] {
    case "scan":
        let limit = args.count >= 3 ? (Int(args[2]) ?? 200) : 200
        try scan(limit: limit)
    case "album":
        guard args.count >= 4 else {
            fail("Albumname oder Foto-IDs fehlen.")
        }
        let albumName = args[2]
        let ids = Array(args.dropFirst(3))
        try addToAlbum(name: albumName, ids: ids)
    case "export":
        guard args.count >= 4 else {
            fail("Foto-ID oder Zielpfad fehlt.")
        }
        let maxSize = args.count >= 5 ? (Int(args[4]) ?? 900) : 900
        try exportPreview(assetId: args[2], destinationPath: args[3], maxSize: maxSize)
    case "status":
        print("ok")
    default:
        fail("Unbekannter Befehl: \(args[1])")
    }
} catch {
    fail("Fotos-Fehler: \(error.localizedDescription)")
}
