import Foundation

struct ServerHealth: Decodable {
    let ok: Bool
    let provider: String
    let activeModel: String

    enum CodingKeys: String, CodingKey {
        case ok, provider
        case activeModel = "active_model"
    }
}

struct ChatResponse: Decodable {
    let answer: String
    let source: String?
    let model: String?
}

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: String
    let content: String
}

struct ProactiveEvent: Decodable, Identifiable, Equatable {
    let id: String
    let trigger: String
    let priority: String
    let message: String
    let reason: String
    let dedupKey: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, trigger, priority, message, reason
        case dedupKey = "dedup_key"
        case createdAt = "created_at"
    }
}

struct ProactiveEventsResponse: Decodable {
    let events: [ProactiveEvent]
}

struct APIError: LocalizedError {
    let statusCode: Int
    let body: String

    var errorDescription: String? {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return "HTTP \(statusCode)"
        }
        return "HTTP \(statusCode): \(trimmed)"
    }
}

enum PairingError: LocalizedError {
    case notPaired

    var errorDescription: String? {
        "Noch nicht mit dem Mac Mini verbunden - bitte zuerst in den Einstellungen koppeln."
    }
}
