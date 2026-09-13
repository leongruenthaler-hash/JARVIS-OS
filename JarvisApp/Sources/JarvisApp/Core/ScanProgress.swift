import Foundation

enum ScanStatus: String, Codable, Equatable {
    case idle
    case preparing
    case scanning
    case indexing
    case downloading
    case completed
    case failed
    case cancelled

    var label: String {
        switch self {
        case .idle: "Bereit"
        case .preparing: "Wird vorbereitet"
        case .scanning: "Scannt"
        case .indexing: "Indexiert"
        case .downloading: "Lädt herunter"
        case .completed: "Fertig"
        case .failed: "Fehler"
        case .cancelled: "Abgebrochen"
        }
    }
}

struct ScanProgress: Codable, Equatable {
    var status: ScanStatus = .idle
    var currentItem: Int = 0
    var totalItems: Int = 0
    var percentage: Double = 0
    var currentLabel: String = ""
    var startedAt: String?
    var finishedAt: String?
    var errorMessage: String?
    var stats: [String: ScanStatValue] = [:]

    var normalizedPercentage: Double {
        max(0, min(100, percentage))
    }

    var fraction: Double {
        normalizedPercentage / 100
    }

    var percentText: String {
        totalItems > 0 ? "\(Int(normalizedPercentage.rounded())) %" : "Wird vorbereitet"
    }
}

enum ScanStatValue: Codable, Equatable, CustomStringConvertible {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else {
            self = .string((try? container.decode(String.self)) ?? "")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        }
    }

    var description: String {
        switch self {
        case .string(let value): value
        case .int(let value): "\(value)"
        case .double(let value): String(format: "%.1f", value)
        case .bool(let value): value ? "aktiv" : "aus"
        }
    }

    var intValue: Int {
        switch self {
        case .int(let value): value
        case .double(let value): Int(value)
        case .bool(let value): value ? 1 : 0
        case .string(let value): Int(value) ?? 0
        }
    }
}

