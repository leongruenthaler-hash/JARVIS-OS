import Foundation
import HealthKit

/// Liest Leons Apple-Health/Watch-Werte per HealthKit aus und schickt sie an
/// den Mac Mini (scripts/health_proxy_server.py, Port 18801) - HealthKit gibt
/// es nur auf iOS, der Mac Mini kann diese Daten nicht selbst abfragen
/// (2026-09-12, Nutzerwunsch "Jarvis soll Zugriff auf meine Körperwerte von
/// der Apple Watch bekommen").
///
/// Bewusst kein Hintergrund-Sync in dieser Version: HKObserverQuery +
/// Background Delivery braucht zusaetzliche Entitlements/Bewilligung und ist
/// auf echten Geraeten unzuverlaessig getaktet - stattdessen synct die App
/// bei jedem Start/Vordergrund-Wechsel (RootView ruft `sync()` auf), plus ein
/// manueller Button in HealthView.
@MainActor
final class HealthKitManager: ObservableObject {
    @Published var lastSyncedAt: Date?
    @Published var lastError: String?
    @Published var isSyncing = false

    private let store = HKHealthStore()

    private let readTypes: Set<HKObjectType> = {
        var types: Set<HKObjectType> = [HKObjectType.workoutType()]
        let quantityIdentifiers: [HKQuantityTypeIdentifier] = [
            .restingHeartRate,
            .heartRateVariabilitySDNN,
            .heartRate,
            .stepCount,
            .activeEnergyBurned,
        ]
        for identifier in quantityIdentifiers {
            if let type = HKObjectType.quantityType(forIdentifier: identifier) {
                types.insert(type)
            }
        }
        if let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            types.insert(sleepType)
        }
        return types
    }()

    var isHealthDataAvailable: Bool {
        HKHealthStore.isHealthDataAvailable()
    }

    func requestAuthorization() async throws {
        guard isHealthDataAvailable else {
            throw HealthKitError.notAvailable
        }
        try await store.requestAuthorization(toShare: [], read: readTypes)
    }

    /// Liest die aktuellen Werte aus und schickt sie an den Proxy. Wird von
    /// RootView bei jedem App-Start/Vordergrund-Wechsel aufgerufen sowie
    /// manuell aus HealthView.
    func sync() async {
        guard isHealthDataAvailable else {
            lastError = "HealthKit ist auf diesem Geraet nicht verfuegbar."
            return
        }
        guard RemoteSettings.healthToken != nil, RemoteSettings.healthBaseURL != nil else {
            return
        }
        isSyncing = true
        defer { isSyncing = false }
        do {
            let snapshot = try await buildSnapshot()
            try await upload(snapshot)
            lastSyncedAt = Date()
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// HKStatisticsQuery (fuer Summen wie Schritte/Aktivkalorien) wirft einen echten
    /// Fehler ("No data available for the specified predicate"), wenn fuer den Typ
    /// ueberhaupt noch keine Samples existieren - anders als HKSampleQuery, das dann
    /// einfach ein leeres Array liefert. Live beobachtet 2026-09-12: ohne dieses
    /// Abfangen kippte ein einzelner noch-leerer Messwert (z.B. frisch verknuepfte
    /// Watch ohne bisherige Schritt-Daten) die GESAMTE Synchronisierung. Jede
    /// Einzelabfrage wird deshalb separat abgefangen, ein fehlender Wert wird `nil`
    /// statt den kompletten Snapshot zu verwerfen.
    private func optional<T>(_ operation: () async throws -> T) async -> T? {
        try? await operation()
    }

    private func buildSnapshot() async throws -> [String: Any] {
        async let sleepHours = optional { try await self.lastNightSleepHours() }
        async let restingHeartRate = optional { try await self.latestQuantitySample(.restingHeartRate, unit: .count().unitDivided(by: .minute())) }
        async let hrv = optional { try await self.latestQuantitySample(.heartRateVariabilitySDNN, unit: .secondUnit(with: .milli)) }
        async let steps = optional { try await self.todaySum(.stepCount, unit: .count()) }
        async let activeEnergy = optional { try await self.todaySum(.activeEnergyBurned, unit: .kilocalorie()) }
        async let workouts = optional { try await self.recentWorkouts(days: 7) }

        let formatter = ISO8601DateFormatter()
        return [
            "updated_at": formatter.string(from: Date()),
            "sleep": ["last_night_hours": (await sleepHours).flatMap { $0 } as Any],
            "heart": [
                "resting_bpm": (await restingHeartRate).flatMap { $0 } as Any,
                "hrv_ms": (await hrv).flatMap { $0 } as Any,
            ],
            "activity": [
                "steps_today": (await steps).flatMap { $0 } as Any,
                "active_energy_kcal_today": (await activeEnergy).flatMap { $0 } as Any,
            ],
            "workouts_last_7_days": (await workouts) ?? [],
        ]
    }

    private func upload(_ snapshot: [String: Any]) async throws {
        guard let baseURL = RemoteSettings.healthBaseURL, let token = RemoteSettings.healthToken else {
            throw HealthKitError.notPaired
        }
        var request = URLRequest(url: baseURL.appendingPathComponent("/api/health/update"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: snapshot)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? ""
            throw HealthKitError.uploadFailed(message)
        }
    }

    // MARK: - HealthKit queries

    private func lastNightSleepHours() async throws -> Double? {
        guard let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else { return nil }
        let now = Date()
        guard let windowStart = Calendar.current.date(byAdding: .hour, value: -36, to: now) else { return nil }
        let predicate = HKQuery.predicateForSamples(withStart: windowStart, end: now, options: .strictStartDate)
        let samples: [HKCategorySample] = try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: sleepType, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: nil) { _, results, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (results as? [HKCategorySample]) ?? [])
                }
            }
            store.execute(query)
        }
        let asleepValues: Set<Int> = [
            HKCategoryValueSleepAnalysis.asleepCore.rawValue,
            HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
            HKCategoryValueSleepAnalysis.asleepREM.rawValue,
            HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue,
        ]
        let totalSeconds = samples
            .filter { asleepValues.contains($0.value) }
            .reduce(0.0) { $0 + $1.endDate.timeIntervalSince($1.startDate) }
        guard totalSeconds > 0 else { return nil }
        return (totalSeconds / 3600.0 * 10).rounded() / 10
    }

    private func latestQuantitySample(_ identifier: HKQuantityTypeIdentifier, unit: HKUnit) async throws -> Double? {
        guard let type = HKObjectType.quantityType(forIdentifier: identifier) else { return nil }
        let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
        let samples: [HKQuantitySample] = try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: type, predicate: nil, limit: 1, sortDescriptors: [sortDescriptor]) { _, results, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (results as? [HKQuantitySample]) ?? [])
                }
            }
            store.execute(query)
        }
        return samples.first?.quantity.doubleValue(for: unit)
    }

    private func todaySum(_ identifier: HKQuantityTypeIdentifier, unit: HKUnit) async throws -> Double? {
        guard let type = HKObjectType.quantityType(forIdentifier: identifier) else { return nil }
        let startOfDay = Calendar.current.startOfDay(for: Date())
        let predicate = HKQuery.predicateForSamples(withStart: startOfDay, end: Date(), options: .strictStartDate)
        let sum: HKQuantity? = try await withCheckedThrowingContinuation { continuation in
            let query = HKStatisticsQuery(quantityType: type, quantitySamplePredicate: predicate, options: .cumulativeSum) { _, statistics, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: statistics?.sumQuantity())
                }
            }
            store.execute(query)
        }
        return sum?.doubleValue(for: unit)
    }

    private func recentWorkouts(days: Int) async throws -> [[String: Any]] {
        guard let windowStart = Calendar.current.date(byAdding: .day, value: -days, to: Date()) else { return [] }
        let predicate = HKQuery.predicateForSamples(withStart: windowStart, end: Date(), options: .strictStartDate)
        let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        let workouts: [HKWorkout] = try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: .workoutType(), predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: [sortDescriptor]) { _, results, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (results as? [HKWorkout]) ?? [])
                }
            }
            store.execute(query)
        }
        let formatter = ISO8601DateFormatter()
        return workouts.map { workout in
            [
                "type": workout.workoutActivityType.displayName,
                "start": formatter.string(from: workout.startDate),
                "duration_min": Int((workout.duration / 60).rounded()),
            ]
        }
    }
}

enum HealthKitError: LocalizedError {
    case notAvailable
    case notPaired
    case uploadFailed(String)

    var errorDescription: String? {
        switch self {
        case .notAvailable:
            return "HealthKit ist auf diesem Geraet nicht verfuegbar."
        case .notPaired:
            return "Kein Mac Mini gekoppelt oder kein Gesundheits-Proxy-Token hinterlegt."
        case .uploadFailed(let message):
            return "Hochladen fehlgeschlagen: \(message)"
        }
    }
}

private extension HKWorkoutActivityType {
    /// Deutsche Kurzbezeichnung fuer die haeufigsten Trainingsarten - kein
    /// Anspruch auf Vollstaendigkeit (HealthKit kennt >80 Typen), faellt fuer
    /// alles Seltenere auf "Training" zurueck statt eine riesige Tabelle zu
    /// pflegen.
    var displayName: String {
        switch self {
        case .running: return "Laufen"
        case .walking: return "Gehen"
        case .cycling: return "Radfahren"
        case .swimming: return "Schwimmen"
        case .traditionalStrengthTraining, .functionalStrengthTraining: return "Krafttraining"
        case .yoga: return "Yoga"
        case .hiking: return "Wandern"
        case .highIntensityIntervalTraining: return "HIIT"
        case .soccer: return "Fußball"
        case .basketball: return "Basketball"
        case .tennis: return "Tennis"
        case .coreTraining: return "Core-Training"
        case .elliptical: return "Crosstrainer"
        case .rowing: return "Rudern"
        default: return "Training"
        }
    }
}
