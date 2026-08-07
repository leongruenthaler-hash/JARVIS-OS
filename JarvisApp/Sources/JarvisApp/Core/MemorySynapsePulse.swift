import Foundation

/// What a travelling light impulse is headed toward - an existing fact node on a ring,
/// or an anonymous point in the outer photos/files field (see MemoryCoreView).
enum PulseTarget: Equatable {
    case node(factID: String)
    case field(type: String, label: String)
}

struct ActivePulse: Identifiable, Equatable {
    let id: String
    let target: PulseTarget
    let startedAt: Date
    let durationSeconds: Double

    func progress(at date: Date) -> Double {
        guard durationSeconds > 0 else { return 1 }
        return min(1, max(0, date.timeIntervalSince(startedAt) / durationSeconds))
    }

    func isFinished(at date: Date) -> Bool {
        progress(at: date) >= 1
    }
}

/// Pure time/state logic (no SwiftUI import) driving MemoryCoreView's "alive" feeling:
/// travelling pulses fire when a fact is new/just used, when a real ActivityEvent
/// (photo/file access) comes in from the backend, and - so the core never looks dead
/// with no fresh activity - occasionally at random for an already-confirmed fact. See
/// plan Design-Entscheidung 4 (docs: plans/2026-08-07-jarvis-memory-neural-network-view.md).
final class MemorySynapsePulseController {
    private(set) var activePulses: [ActivePulse] = []

    private var seenFactUpdatedAt: [String: String] = [:]
    private var seenActivityIDs: Set<String> = []
    private var nextBackgroundFireAt: Date?

    private let pulseDuration: Double = 1.1
    private let backgroundIntervalRange: ClosedRange<Double> = 5...8

    func syncTriggeredPulses(facts: [MemoryFact], now: Date) {
        for fact in facts {
            let stamp = fact.updatedAt
            let previous = seenFactUpdatedAt[fact.id]
            seenFactUpdatedAt[fact.id] = stamp
            guard previous != nil, previous != stamp else {
                if previous == nil { seenFactUpdatedAt[fact.id] = stamp }
                continue
            }
            fire(target: .node(factID: fact.id), now: now)
        }
    }

    func syncActivityEvents(_ events: [ActivityEvent], now: Date) {
        for event in events {
            guard !seenActivityIDs.contains(event.id) else { continue }
            seenActivityIDs.insert(event.id)
            if event.type == "memory", let reference = event.reference {
                fire(target: .node(factID: reference), now: now)
            } else {
                fire(target: .field(type: event.type, label: event.label), now: now)
            }
        }
        // Unbounded growth guard - activity IDs are unique per (type, at, label), so a
        // long-running session would otherwise accumulate this set forever.
        if seenActivityIDs.count > 500 {
            seenActivityIDs.removeAll()
        }
    }

    func maybeFireBackgroundPulse(facts: [MemoryFact], now: Date) {
        guard !facts.isEmpty else { return }
        if nextBackgroundFireAt == nil {
            nextBackgroundFireAt = now.addingTimeInterval(.random(in: backgroundIntervalRange))
            return
        }
        guard let due = nextBackgroundFireAt, now >= due else { return }
        nextBackgroundFireAt = now.addingTimeInterval(.random(in: backgroundIntervalRange))
        let confirmed = facts.filter { $0.status == "confirmed" }
        guard let chosen = (confirmed.isEmpty ? facts : confirmed).randomElement() else { return }
        fire(target: .node(factID: chosen.id), now: now)
    }

    func purgeFinished(now: Date) {
        activePulses.removeAll { $0.isFinished(at: now) }
    }

    private func fire(target: PulseTarget, now: Date) {
        activePulses.append(
            ActivePulse(id: UUID().uuidString, target: target, startedAt: now, durationSeconds: pulseDuration)
        )
    }
}
