import Foundation
import SwiftUI

let jarvisAppVersion = "Beta 0.1"

enum JarvisSection: String, CaseIterable, Identifiable {
    case home = "Home"
    case actions = "Aktionszentrale"
    case chat = "Chat"
    case history = "Verlauf"
    case calendar = "Kalender"
    case mail = "Mail"
    case reminders = "Erinnerungen"
    case files = "Dateien"
    case photos = "Fotos"
    case privacy = "Datenschutz"
    case models = "Modelle"
    case settings = "Einstellungen"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .home: "house.fill"
        case .actions: "rectangle.grid.2x2.fill"
        case .chat: "bubble.left.and.bubble.right"
        case .history: "clock.arrow.circlepath"
        case .calendar: "calendar"
        case .mail: "envelope"
        case .reminders: "checklist"
        case .files: "folder"
        case .photos: "photo.on.rectangle"
        case .privacy: "hand.raised"
        case .models: "cpu"
        case .settings: "gearshape"
        }
    }
}

enum JarvisRuntimeStatus: String {
    case idle = "Verbunden"
    case listening = "Zuhören"
    case transcribing = "Transkribieren"
    case thinking = "Denkt nach"
    case responding = "Antwortet"
    case offline = "Nicht verbunden"
}

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: Role
    var text: String
    let date = Date()

    enum Role: Equatable {
        case user
        case jarvis
        case system
    }
}

struct ModelStatus: Codable, Equatable {
    var provider: String = "ollama"
    var activeModel: String = "phi4-mini"
    var mode: String = "performance"
    var openAIEnabled: Bool = false
    var ollamaInstalled: Bool = false
    var ollamaRunning: Bool = false
    var installedModels: [String] = []
    var missingModels: [String] = []
    var openAIKeyPresent: Bool = false

    enum CodingKeys: String, CodingKey {
        case provider
        case activeModel = "active_model"
        case mode
        case openAIEnabled = "openai_enabled"
        case ollamaInstalled = "ollama_installed"
        case ollamaRunning = "ollama_running"
        case installedModels = "installed_models"
        case missingModels = "missing_models"
        case openAIKeyPresent = "openai_key_present"
    }
}

struct ServerHealth: Codable {
    let ok: Bool
    let provider: String
    let activeModel: String
    let openAIEnabled: Bool
    let ollamaInstalled: Bool
    let ollamaRunning: Bool

    enum CodingKeys: String, CodingKey {
        case ok, provider
        case activeModel = "active_model"
        case openAIEnabled = "openai_enabled"
        case ollamaInstalled = "ollama_installed"
        case ollamaRunning = "ollama_running"
    }
}

struct PermissionInfo: Codable, Equatable, Identifiable {
    var id: String { name }
    let name: String
    let allowed: Bool
    let explanation: String
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case name
        case allowed
        case explanation
        case updatedAt = "updated_at"
    }
}

struct FileSearchPayload: Codable, Equatable {
    let query: String
    let message: String
    let results: [FileSearchResult]
}

struct FileSearchResult: Codable, Identifiable, Equatable {
    let name: String
    let kind: String
    let root: String
    let relativePath: String
    let path: String
    let modified: String
    let size: Int
    let fileExtension: String

    var id: String {
        if !path.isEmpty { return path }
        return [root, relativePath, name].joined(separator: "/")
    }

    var isFolder: Bool {
        kind == "folder"
    }

    var kindLabel: String {
        isFolder ? "Ordner" : "Datei"
    }

    var rootLabel: String {
        switch root.lowercased() {
        case "desktop", "schreibtisch": return "Schreibtisch"
        case "documents", "dokumente": return "Dokumente"
        case "downloads", "download": return "Downloads"
        case "jarvis", "projekt": return "Jarvis"
        default: return root.isEmpty ? "Lokaler Index" : root
        }
    }

    var locationLabel: String {
        let parent = URL(fileURLWithPath: relativePath).deletingLastPathComponent().path
        if parent.isEmpty || parent == "." || parent == "/" {
            return rootLabel
        }
        return "\(rootLabel)/\(parent.trimmingCharacters(in: CharacterSet(charactersIn: "/")))"
    }

    enum CodingKeys: String, CodingKey {
        case name
        case kind
        case root
        case relativePath = "relative_path"
        case path
        case modified
        case size
        case fileExtension = "extension"
    }
}
