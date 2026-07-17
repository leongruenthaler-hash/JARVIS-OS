import Foundation

struct WeatherSnapshot: Codable, Equatable {
    let temperature: Double
    let weatherCode: Int
    let isDay: Bool
    let windSpeed: Double
    let fetchedAt: Date
}

struct GeocodedLocation: Codable, Equatable {
    let latitude: Double
    let longitude: Double
    let resolvedName: String
}

enum WeatherServiceError: LocalizedError {
    case cityNotFound
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .cityNotFound: return "Stadt nicht gefunden."
        case .invalidResponse: return "Wetterdaten konnten nicht geladen werden."
        }
    }
}

/// Open-Meteo-backed weather data source (dashboard-theme, Datenquelle 2/4). No API key
/// needed for non-commercial use (verified against open-meteo.com/en/docs and /en/terms:
/// free tier allows 600 requests/minute, 5'000/hour, 10'000/day - far more than a beta
/// needs). Requires CC BY 4.0 attribution, surfaced in LicensesView.
///
/// Deliberately splits one-time geocoding (city name -> coordinates, only on setup/change)
/// from the regular weather fetch (coordinates -> conditions, cached) - geocoding must
/// never run on every weather poll, only when the user sets/changes their city.
actor WeatherService {
    static let shared = WeatherService()

    private var cachedSnapshot: WeatherSnapshot?
    private var cachedLocation: GeocodedLocation?
    private let minimumFetchInterval: TimeInterval = 20 * 60

    /// One-time (or on-change) lookup: city name -> coordinates. Only ever called from
    /// Settings when the user sets/changes their city - never from currentWeather().
    func geocodeCity(_ name: String) async throws -> GeocodedLocation {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw WeatherServiceError.cityNotFound }

        var components = URLComponents(string: "https://geocoding-api.open-meteo.com/v1/search")!
        components.queryItems = [
            URLQueryItem(name: "name", value: trimmed),
            URLQueryItem(name: "count", value: "1"),
            URLQueryItem(name: "language", value: "de"),
            URLQueryItem(name: "format", value: "json")
        ]
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw WeatherServiceError.invalidResponse
        }

        struct GeocodeResponse: Decodable {
            struct Result: Decodable {
                let latitude: Double
                let longitude: Double
                let name: String
                let country: String?
            }
            let results: [Result]?
        }
        let decoded = try JSONDecoder().decode(GeocodeResponse.self, from: data)
        guard let first = decoded.results?.first else { throw WeatherServiceError.cityNotFound }

        let resolvedName = [first.name, first.country].compactMap { $0 }.joined(separator: ", ")
        return GeocodedLocation(latitude: first.latitude, longitude: first.longitude, resolvedName: resolvedName)
    }

    /// Regular weather fetch: returns a cached snapshot if it's still fresh (< 20 minutes
    /// old) AND for the same location, otherwise fetches fresh. `forceRefresh` bypasses the
    /// cache (e.g. right after the user changes their city).
    func currentWeather(for location: GeocodedLocation, forceRefresh: Bool = false) async throws -> WeatherSnapshot {
        if !forceRefresh,
           let cached = cachedSnapshot,
           let cachedLoc = cachedLocation,
           cachedLoc == location,
           Date().timeIntervalSince(cached.fetchedAt) < minimumFetchInterval {
            return cached
        }

        var components = URLComponents(string: "https://api.open-meteo.com/v1/forecast")!
        components.queryItems = [
            URLQueryItem(name: "latitude", value: String(location.latitude)),
            URLQueryItem(name: "longitude", value: String(location.longitude)),
            URLQueryItem(name: "current", value: "temperature_2m,weather_code,is_day,wind_speed_10m"),
            URLQueryItem(name: "timezone", value: "auto")
        ]
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw WeatherServiceError.invalidResponse
        }

        struct ForecastResponse: Decodable {
            struct Current: Decodable {
                let temperature_2m: Double
                let weather_code: Int
                let is_day: Int
                let wind_speed_10m: Double
            }
            let current: Current
        }
        let decoded = try JSONDecoder().decode(ForecastResponse.self, from: data)
        let snapshot = WeatherSnapshot(
            temperature: decoded.current.temperature_2m,
            weatherCode: decoded.current.weather_code,
            isDay: decoded.current.is_day == 1,
            windSpeed: decoded.current.wind_speed_10m,
            fetchedAt: Date()
        )
        cachedSnapshot = snapshot
        cachedLocation = location
        return snapshot
    }
}
