import Foundation

/// Every request carries a per-process shared secret (`X-Jarvis-Token`) that the Python
/// backend generates on startup and writes to a 0600 file in the same Application Support
/// directory the app already uses for venv/memory/config. Without this, any webpage open
/// in the user's browser could blindly POST to 127.0.0.1:8765 (permissions, the OpenAI key,
/// mail/calendar actions, privacy-log deletion, ...) since the server has no other way to
/// tell "the Mac app" apart from "any local process/page". The token is unknown to a remote
/// attacker and isn't guessable, so unauthenticated requests are simply rejected (401).
struct JarvisAPIClient {
    var baseURL = URL(string: "http://127.0.0.1:8765")!

    private static var cachedToken: String?

    private static var tokenFilePath: String {
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        let identifier = Bundle.main.bundleIdentifier ?? "com.leon.jarvis"
        return base.appendingPathComponent(identifier).appendingPathComponent("local_server.token").path
    }

    /// Reads the token written by `local_server.py`'s `run()`. Cached in memory so normal
    /// requests don't hit disk each time; `forceRefresh` re-reads after a 401, which happens
    /// whenever the Python process has (re)started since the token was cached.
    private func loadToken(forceRefresh: Bool = false) -> String? {
        if !forceRefresh, let cached = Self.cachedToken {
            return cached
        }
        guard let data = FileManager.default.contents(atPath: Self.tokenFilePath),
              let token = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !token.isEmpty else {
            return nil
        }
        Self.cachedToken = token
        return token
    }

    func health() async throws -> ServerHealth {
        try await get("/api/health")
    }

    func sendChat(_ message: String, history: [[String: String]] = []) async throws -> ChatResponse {
        struct Request: Encodable { let message: String; let history: [[String: String]] }
        let response: ChatResponse = try await post("/api/chat", body: Request(message: message, history: history))
        return response
    }

    func sendChatStream(_ message: String, history: [[String: String]] = [], onChunk: @MainActor @escaping (String) -> Void) async throws -> String {
        struct Request: Encodable { let message: String; let history: [[String: String]] }
        var request = try makePostRequest("/api/chat/stream", body: Request(message: message, history: history))
        request.timeoutInterval = 90
        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        try validate(response)

        var complete = ""
        for try await line in bytes.lines {
            guard let data = line.data(using: .utf8), !data.isEmpty else { continue }
            let chunk = try JSONDecoder().decode(StreamChunk.self, from: data)
            if !chunk.chunk.isEmpty {
                complete += chunk.chunk
                await onChunk(chunk.chunk)
            }
            if chunk.done { break }
        }
        return complete
    }

    func listenAndRespond(history: [[String: String]] = []) async throws -> ListenResponse {
        struct Request: Encodable { let history: [[String: String]] }
        return try await post("/api/listen", body: Request(history: history))
    }


    func transcribeVoice(audioPath: String, sampleRate: Double) async throws -> VoiceTranscriptionResponse {
        struct Request: Encodable {
            let audioPath: String
            let sampleRate: Double

            enum CodingKeys: String, CodingKey {
                case audioPath = "audio_path"
                case sampleRate = "sample_rate"
            }
        }
        // First-ever voice request can trigger a slow, one-time STT model load/download
        // (see LocalServerController voice-bootstrap status) - matches that timeframe
        // instead of the default 60s, so it doesn't time out mid-load.
        return try await post("/api/voice/transcribe", body: Request(audioPath: audioPath, sampleRate: sampleRate), timeoutInterval: 1200)
    }

    func prewarmVoicePipeline() async throws -> PrewarmResponse {
        try await post("/api/voice/prewarm", body: EmptyBody())
    }

    func cancelListening() async throws {
        struct Response: Decodable { let ok: Bool }
        let _: Response = try await post("/api/voice/cancel-listening", body: EmptyBody())
    }

    func setVoiceSpeakingState(_ isSpeaking: Bool) async throws {
        struct Request: Encodable { let speaking: Bool }
        struct Response: Decodable { let ok: Bool }
        let _: Response = try await post("/api/voice/speaking", body: Request(speaking: isSpeaking))
    }

    func models() async throws -> ModelStatus {
        try await get("/api/models")
    }

    func scanStatus() async throws -> ScanStatusBundle {
        try await post("/api/scan-status", body: EmptyBody())
    }

    func startMailFolderScan() async throws -> ScanProgress {
        try await post("/api/mail/scan-folders", body: EmptyBody())
    }

    func startMailBackgroundScan() async throws -> ScanProgress {
        try await post("/api/mail/background-start", body: EmptyBody())
    }

    func pendingCalendarActions() async throws -> [PendingCalendarAction] {
        let response: PendingCalendarActionsResponse = try await get("/api/mail/pending-calendar-actions")
        return response.actions
    }

    @discardableResult
    func resolveCalendarAction(actionKey: String, approve: Bool) async throws -> Bool {
        struct Request: Encodable { let actionKey: String; let approve: Bool
            enum CodingKeys: String, CodingKey { case actionKey = "action_key"; case approve }
        }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/mail/calendar-actions/resolve", body: Request(actionKey: actionKey, approve: approve))
        return response.ok
    }

    func startPhotoIndexScan() async throws -> ScanProgress {
        try await post("/api/photos/scan", body: EmptyBody())
    }

    func startLocalPhotoVisionAnalysis() async throws -> ScanProgress {
        try await post("/api/photos/vision/analyze", body: EmptyBody())
    }

    func resetLocalPhotoVisionDescriptions() async throws -> ScanProgress {
        try await post("/api/photos/vision/reset", body: EmptyBody())
    }

    func localPhotoVisionStatus() async throws -> LocalVisionStatus {
        try await get("/api/photos/vision-status")
    }

    func calendarOverview() async throws -> CalendarOverviewPayload {
        try await get("/api/calendar/overview")
    }

    func mailOverview() async throws -> MailOverviewPayload {
        try await get("/api/mail/overview")
    }

    func musicOverview() async throws -> MusicOverviewPayload {
        try await get("/api/music/overview")
    }

    func conversationHistory() async throws -> ConversationHistoryPayload {
        try await get("/api/conversation-history")
    }

    func dailyBriefing() async throws -> DailyBriefingPayload {
        try await post("/api/daily-briefing", body: EmptyBody())
    }

    func startFileIndexScan() async throws -> ScanProgress {
        try await post("/api/files/scan", body: EmptyBody())
    }

    func searchFiles(query: String) async throws -> FileSearchPayload {
        struct Request: Encodable { let query: String }
        return try await post("/api/files/search", body: Request(query: query))
    }

    func moveFileSearchResults(query: String, targetFolder: String) async throws -> String {
        struct Request: Encodable {
            let query: String
            let targetFolder: String

            enum CodingKeys: String, CodingKey {
                case query
                case targetFolder = "target_folder"
            }
        }
        struct Response: Decodable {
            let message: String
            let progress: ScanProgress?
        }
        let response: Response = try await post(
            "/api/files/move-search-results",
            body: Request(query: query, targetFolder: targetFolder)
        )
        return response.message
    }

    func resetFileIndex() async throws -> ScanProgress {
        try await post("/api/files/reset", body: EmptyBody())
    }

    func requestPhotoPermission() async throws -> String {
        struct Response: Decodable { let message: String; let progress: ScanProgress? }
        let response: Response = try await post("/api/photos/permission", body: EmptyBody())
        return response.message
    }

    func resetPhotoIndex() async throws -> ScanProgress {
        try await post("/api/photos/reset", body: EmptyBody())
    }

    func photoPermissionStatus() async throws -> String {
        struct Response: Decodable { let status: String }
        let response: Response = try await get("/api/photos/permission-status")
        return response.status
    }

    func setModel(provider: String? = nil, model: String? = nil) async throws -> ModelStatus {
        struct Request: Encodable { let provider: String?; let model: String? }
        struct Response: Decodable { let message: String; let status: ModelStatus }
        let response: Response = try await post("/api/models", body: Request(provider: provider, model: model))
        return response.status
    }

    func pullModel(_ model: String) async throws -> ScanProgress {
        struct Request: Encodable { let model: String }
        return try await post("/api/models/pull", body: Request(model: model))
    }

    func setFastVoiceMode(_ enabled: Bool) async throws {
        struct Request: Encodable { let enabled: Bool }
        struct Response: Decodable { let ok: Bool; let enabled: Bool }
        let _: Response = try await post("/api/settings/fast-voice-mode", body: Request(enabled: enabled))
    }

    func setStoreConversation(_ enabled: Bool) async throws {
        struct Request: Encodable { let enabled: Bool }
        struct Response: Decodable { let ok: Bool; let enabled: Bool }
        let _: Response = try await post("/api/settings/store-conversation", body: Request(enabled: enabled))
    }

    func setVoice(_ voice: String) async throws {
        struct Request: Encodable { let voice: String }
        struct Response: Decodable { let ok: Bool; let voice: String }
        let _: Response = try await post("/api/settings/voice", body: Request(voice: voice))
    }

    func privacyStatus() async throws -> String {
        struct Response: Decodable { let status: String }
        let response: Response = try await get("/api/privacy/status")
        return response.status
    }

    func permissions() async throws -> [String: PermissionInfo] {
        let payloads: [String: PermissionPayload] = try await get("/api/permissions")
        return Self.decodePermissions(payloads)
    }

    func setPermission(_ permission: String, allowed: Bool) async throws -> [String: PermissionInfo] {
        struct Request: Encodable { let permission: String; let allowed: Bool }
        struct Response: Decodable { let permissions: [String: PermissionPayload] }
        let response: Response = try await post("/api/permissions", body: Request(permission: permission, allowed: allowed))
        return Self.decodePermissions(response.permissions)
    }

    private static func decodePermissions(_ payloads: [String: PermissionPayload]) -> [String: PermissionInfo] {
        var result: [String: PermissionInfo] = [:]
        for (name, payload) in payloads {
            result[name] = PermissionInfo(
                name: name,
                allowed: payload.allowed,
                explanation: payload.explanation,
                updatedAt: payload.updatedAt
            )
        }
        return result
    }

    func setOpenAIKey(_ apiKey: String) async throws {
        struct Request: Encodable { let api_key: String }
        struct Response: Decodable { let ok: Bool }
        let _: Response = try await post("/api/openai-key/set", body: Request(api_key: apiKey))
    }

    func deleteOpenAIKey() async throws {
        struct Response: Decodable { let deleted: Bool }
        let _: Response = try await post("/api/openai-key/delete", body: EmptyBody())
    }

    func exportPrivacyData() async throws -> String {
        struct Response: Decodable { let path: String }
        let response: Response = try await post("/api/privacy/export", body: EmptyBody())
        return response.path
    }

    func deleteHistory() async throws -> String {
        struct Response: Decodable { let message: String }
        let response: Response = try await post("/api/privacy/delete-history", body: EmptyBody())
        return response.message
    }

    func clearLogs() async throws -> String {
        struct Response: Decodable { let message: String }
        let response: Response = try await post("/api/privacy/clear-logs", body: EmptyBody())
        return response.message
    }

    func memoryFacts(search: String = "", category: String = "") async throws -> MemoryFactsResponse {
        var components = URLComponents()
        var items: [URLQueryItem] = []
        if !search.isEmpty { items.append(URLQueryItem(name: "search", value: search)) }
        if !category.isEmpty { items.append(URLQueryItem(name: "category", value: category)) }
        components.queryItems = items.isEmpty ? nil : items
        let query = components.percentEncodedQuery.map { "?\($0)" } ?? ""
        return try await get("/api/memory/facts" + query)
    }

    @discardableResult
    func updateMemoryFact(id: String, fields: [String: String]) async throws -> Bool {
        struct Response: Decodable { let ok: Bool }
        var body: [String: String] = fields
        body["id"] = id
        let response: Response = try await post("/api/memory/facts/update", body: body)
        return response.ok
    }

    @discardableResult
    func confirmMemoryFact(id: String) async throws -> Bool {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/memory/facts/confirm", body: Request(id: id))
        return response.ok
    }

    @discardableResult
    func rejectMemoryFact(id: String) async throws -> Bool {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/memory/facts/reject", body: Request(id: id))
        return response.ok
    }

    @discardableResult
    func deleteMemoryFact(id: String) async throws -> Bool {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/memory/facts/delete", body: Request(id: id))
        return response.ok
    }

    func recentActivity(since: TimeInterval) async throws -> [ActivityEvent] {
        var components = URLComponents()
        components.queryItems = [URLQueryItem(name: "since", value: String(since))]
        let query = components.percentEncodedQuery.map { "?\($0)" } ?? ""
        let response: ActivityEventsResponse = try await get("/api/activity/recent" + query)
        return response.events
    }

    func proactivityEvents() async throws -> [ProactiveEvent] {
        let response: ProactiveEventsResponse = try await get("/api/proactivity/events")
        return response.events
    }

    @discardableResult
    func snoozeProactivityEvent(dedupKey: String, minutes: Int = 60) async throws -> Bool {
        struct Request: Encodable { let dedupKey: String; let minutes: Int
            enum CodingKeys: String, CodingKey { case dedupKey = "dedup_key"; case minutes }
        }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/proactivity/snooze", body: Request(dedupKey: dedupKey, minutes: minutes))
        return response.ok
    }

    @discardableResult
    func dismissProactivityEvent(dedupKey: String) async throws -> Bool {
        struct Request: Encodable { let dedupKey: String
            enum CodingKeys: String, CodingKey { case dedupKey = "dedup_key" }
        }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/proactivity/dismiss", body: Request(dedupKey: dedupKey))
        return response.ok
    }

    func tasks(status: String = "", project: String = "") async throws -> JarvisTasksResponse {
        var components = URLComponents()
        var items: [URLQueryItem] = []
        if !status.isEmpty { items.append(URLQueryItem(name: "status", value: status)) }
        if !project.isEmpty { items.append(URLQueryItem(name: "project", value: project)) }
        components.queryItems = items.isEmpty ? nil : items
        let query = components.percentEncodedQuery.map { "?\($0)" } ?? ""
        return try await get("/api/tasks" + query)
    }

    struct CreateTaskRequest: Encodable {
        let title: String
        let project: String?
        let priority: String
        let deadline: String?
    }

    func createTask(_ request: CreateTaskRequest) async throws -> JarvisTask? {
        struct Response: Decodable { let ok: Bool; let task: JarvisTask? }
        let response: Response = try await post("/api/tasks/create", body: request)
        return response.task
    }

    @discardableResult
    func updateTask(id: String, fields: [String: String]) async throws -> Bool {
        struct Response: Decodable { let ok: Bool }
        var body: [String: String] = fields
        body["id"] = id
        let response: Response = try await post("/api/tasks/update", body: body)
        return response.ok
    }

    @discardableResult
    func confirmTask(id: String) async throws -> Bool {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/tasks/confirm", body: Request(id: id))
        return response.ok
    }

    @discardableResult
    func rejectTask(id: String) async throws -> Bool {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/tasks/reject", body: Request(id: id))
        return response.ok
    }

    @discardableResult
    func deleteTask(id: String) async throws -> Bool {
        struct Request: Encodable { let id: String }
        struct Response: Decodable { let ok: Bool }
        let response: Response = try await post("/api/tasks/delete", body: Request(id: id))
        return response.ok
    }

    func voiceModeStatus() async throws -> VoiceModeStatus {
        try await get("/api/settings/voice-mode")
    }

    @discardableResult
    func setVoiceMode(_ mode: String) async throws -> String {
        struct Request: Encodable { let mode: String }
        struct Response: Decodable { let ok: Bool; let mode: String }
        let response: Response = try await post("/api/settings/voice-mode", body: Request(mode: mode))
        return response.mode
    }

    /// Fire-and-forget: only numeric millisecond durations, never transcript/audio
    /// content - see app/core/voice_performance.py.
    func recordVoicePerformance(_ metrics: [String: Int]) async throws {
        struct Response: Decodable { let ok: Bool }
        let _: Response = try await post("/api/voice/performance-report", body: metrics)
    }

    private func get<T: Decodable>(_ path: String, retryingAuth: Bool = true) async throws -> T {
        var request = URLRequest(url: makeURL(path))
        if let token = loadToken() {
            request.setValue(token, forHTTPHeaderField: "X-Jarvis-Token")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        if retryingAuth, (response as? HTTPURLResponse)?.statusCode == 401, loadToken(forceRefresh: true) != nil {
            return try await get(path, retryingAuth: false)
        }
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B, timeoutInterval: TimeInterval? = nil, retryingAuth: Bool = true) async throws -> T {
        var request = try makePostRequest(path, body: body)
        if let timeoutInterval { request.timeoutInterval = timeoutInterval }
        let (data, response) = try await URLSession.shared.data(for: request)
        if retryingAuth, (response as? HTTPURLResponse)?.statusCode == 401, loadToken(forceRefresh: true) != nil {
            return try await post(path, body: body, timeoutInterval: timeoutInterval, retryingAuth: false)
        }
        try validate(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func makePostRequest<B: Encodable>(_ path: String, body: B) throws -> URLRequest {
        let url = makeURL(path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = loadToken() {
            request.setValue(token, forHTTPHeaderField: "X-Jarvis-Token")
        }
        request.httpBody = try JSONEncoder().encode(body)
        return request
    }

    private func makeURL(_ path: String) -> URL {
        URL(string: path.hasPrefix("/") ? path : "/" + path, relativeTo: baseURL)!.absoluteURL
    }

    private func validate(_ response: URLResponse, data: Data? = nil) throws {
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            let body = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            throw APIError(statusCode: http.statusCode, body: body)
        }
    }
}

private struct PermissionPayload: Decodable {
    let allowed: Bool
    let explanation: String
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case allowed
        case explanation
        case updatedAt = "updated_at"
    }
}

private struct APIError: LocalizedError {
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

private struct EmptyBody: Encodable {}

private struct StreamChunk: Decodable {
    let chunk: String
    let done: Bool
}

struct ListenResponse: Decodable {
    let transcript: String
    let answer: String
    let status: String
    let source: String?
    let model: String?
}

struct PrewarmResponse: Decodable {
    let ok: Bool
    let duration: Double
    let message: String
}

struct ChatResponse: Decodable {
    let answer: String
    let source: String?
    let model: String?
}

struct LocalVisionStatus: Decodable, Equatable {
    let available: Bool
    let model: String
    let installedModels: [String]
    let message: String

    enum CodingKeys: String, CodingKey {
        case available
        case model
        case installedModels = "installed_models"
        case message
    }
}

struct CalendarOverviewPayload: Decodable, Equatable {
    let calendar: CalendarOverviewSection
    let reminders: CalendarOverviewSection
}

struct DailyBriefingPayload: Decodable, Equatable {
    let briefing: String
    let calendarCount: Int
    let remindersCount: Int

    enum CodingKeys: String, CodingKey {
        case briefing
        case calendarCount = "calendar_count"
        case remindersCount = "reminders_count"
    }
}

struct ConversationHistoryPayload: Decodable, Equatable {
    let recordingEnabled: Bool
    let turns: [ConversationTurnPayload]

    enum CodingKeys: String, CodingKey {
        case recordingEnabled = "recording_enabled"
        case turns
    }
}

struct ConversationTurnPayload: Decodable, Equatable, Identifiable {
    let role: String
    let content: String
    let createdAt: String

    var id: String { createdAt + role + content.prefix(20) }

    enum CodingKeys: String, CodingKey {
        case role
        case content
        case createdAt = "created_at"
    }
}

struct CalendarOverviewSection: Decodable, Equatable {
    let items: [CalendarOverviewItem]
    let count: Int
    let message: String
    let error: String
}

struct CalendarOverviewItem: Decodable, Identifiable, Equatable {
    let calendar: String?
    let list: String?
    let title: String
    let start: String?
    let end: String?
    let due: String?

    var id: String {
        [calendar ?? list ?? "", title, start ?? due ?? ""].joined(separator: "|")
    }
}

struct MailOverviewPayload: Decodable, Equatable {
    let unreadCount: Int
    let messages: [MailOverviewMessage]
    let message: String
    let error: String

    enum CodingKeys: String, CodingKey {
        case unreadCount = "unread_count"
        case messages, message, error
    }
}

struct MailOverviewMessage: Decodable, Identifiable, Equatable {
    let sender: String
    let subject: String

    var id: String { sender + "|" + subject }
}

struct MusicOverviewPayload: Decodable, Equatable {
    let track: MusicTrack?
    let message: String
    let error: String
}

struct MusicTrack: Decodable, Equatable {
    let title: String
    let artist: String?
    let album: String?
    let isPlaying: Bool

    enum CodingKeys: String, CodingKey {
        case title, artist, album
        case isPlaying = "is_playing"
    }
}

struct VoiceTranscriptionResponse: Decodable {
    let transcript: String
    let duration: Double?
    let speechDuration: Double?
    let sampleRate: Double?
    let source: String?
    let model: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case transcript
        case duration
        case speechDuration = "speech_duration"
        case sampleRate = "sample_rate"
        case source
        case model
        case error
    }
}
