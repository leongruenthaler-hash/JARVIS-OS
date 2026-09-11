import Foundation

/// OpenClaw's Gateway /health is much simpler than the old Jarvis backend's
/// (just liveness, no provider/model info) - those details now live in the
/// chat completion response instead.
struct ServerHealth: Decodable {
    let ok: Bool
    let status: String
}

/// OpenAI-compatible chat completions wire format (OpenClaw Gateway
/// /v1/chat/completions, enabled via gateway.http.endpoints.chatCompletions).
struct ChatCompletionRequest: Encodable {
    let model: String
    let messages: [ChatCompletionMessage]
    let user: String
}

struct ChatCompletionMessage: Codable {
    let role: String
    let content: String
}

struct ChatCompletionResponse: Decodable {
    struct Choice: Decodable {
        let message: ChatCompletionMessage
    }
    let choices: [Choice]
}

struct ChatResponse {
    let answer: String
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
