import Foundation

private struct DailyUsage: Codable, Equatable {
    let dateKey: String
    let activeSeconds: Double
}

/// Tracks Jarvis's OWN active interaction time per day (dashboard-theme, Datenquelle 4/4) -
/// deliberately NOT a general "productivity" score. Measures only the span of an actual
/// chat/voice turn (`AppState.streamAndSpeakAnswer`, which already covers both text
/// generation and any streamed speech playback) - no system-wide activity tracking, no
/// other-app monitoring, no judgement of "good" or "bad" usage. The dashboard card built on
/// top of this must stay a neutral info display, not an ansporn/pressure element - see the
/// card implementation for that framing.
///
/// The daily goal is intentionally NOT defaulted to any built-in number - `dailyGoalMinutes()`
/// returns `nil` until the user explicitly sets one in Settings, so the app never implies an
/// "expected" usage amount nobody asked for.
enum ProductivityTracker {
    private static let storageKey = "JarvisDailyUsageSeconds"
    private static let goalKey = "JarvisDailyUsageGoalMinutes"

    private static func todayKey(_ date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = .current
        return formatter.string(from: date)
    }

    /// Adds `seconds` of active interaction time to today's running total, rolling over to a
    /// fresh count if the stored total is from a previous day. Call once per finished turn.
    static func recordInteraction(seconds: TimeInterval) {
        guard seconds > 0 else { return }
        let key = todayKey()
        let usage = storedUsage()
        let updated: DailyUsage
        if usage.dateKey == key {
            updated = DailyUsage(dateKey: key, activeSeconds: usage.activeSeconds + seconds)
        } else {
            updated = DailyUsage(dateKey: key, activeSeconds: seconds)
        }
        persist(updated)
    }

    /// Today's active usage in minutes; 0 if nothing recorded yet or the stored value is from
    /// a previous day (no rollover carried forward - always resets at day boundary).
    static func todayActiveMinutes() -> Double {
        let usage = storedUsage()
        guard usage.dateKey == todayKey() else { return 0 }
        return usage.activeSeconds / 60
    }

    /// User-set daily goal in minutes, or `nil` if never configured.
    static func dailyGoalMinutes() -> Double? {
        guard UserDefaults.standard.object(forKey: goalKey) != nil else { return nil }
        let value = UserDefaults.standard.double(forKey: goalKey)
        return value > 0 ? value : nil
    }

    /// Pass `nil` (or any non-positive value) to clear the goal back to "not configured".
    static func setDailyGoalMinutes(_ minutes: Double?) {
        if let minutes, minutes > 0 {
            UserDefaults.standard.set(minutes, forKey: goalKey)
        } else {
            UserDefaults.standard.removeObject(forKey: goalKey)
        }
    }

    private static func storedUsage() -> DailyUsage {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let usage = try? JSONDecoder().decode(DailyUsage.self, from: data) else {
            return DailyUsage(dateKey: todayKey(), activeSeconds: 0)
        }
        return usage
    }

    private static func persist(_ usage: DailyUsage) {
        guard let data = try? JSONEncoder().encode(usage) else { return }
        UserDefaults.standard.set(data, forKey: storageKey)
    }
}
