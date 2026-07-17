import Foundation

struct NowPlayingInfo: Equatable {
    let title: String
    let artist: String?
    let album: String?
    let appName: String?
    let isPlaying: Bool?
}

/// Queries the system-wide "Now Playing" info via the private MediaRemote framework's
/// `MRNowPlayingRequest` class - works across ANY media app (Apple Music, Spotify, Safari,
/// podcast apps, etc.), not tied to one provider, unlike `music_client.py`'s Apple-Music-
/// only AppleScript control (dashboard-theme, Datenquelle 3/4).
///
/// UNDOCUMENTED PRIVATE API - important to keep in mind for the future:
/// - `MediaRemote.framework` has no public header; this uses dynamic Obj-C message sending
///   (`NSClassFromString` + `perform(_:)`) to call methods Apple never published, the same
///   technique used by several open-source "now playing" tools (verified via a live JXA
///   test on this machine before implementing, matching this Swift port exactly).
/// - There are recent reports (mid-2026) that Apple has started restricting the older,
///   simpler `MRMediaRemoteGetNowPlayingInfo()` C function for third-party processes on
///   some macOS versions. The class-based approach used here (`MRNowPlayingRequest`) was
///   empirically confirmed still working on this machine's current macOS version, but a
///   future OS update could break this without warning - there is no way to "fix" a
///   private API break other than finding a new workaround if/when Apple changes it.
/// - Every step degrades gracefully to `nil` (missing bundle, missing class, method not
///   responding, wrong return type) rather than crashing - a future breakage would just
///   make the dashboard's music card show "nothing playing" instead of failing loudly.
enum NowPlayingService {
    static func currentInfo() -> NowPlayingInfo? {
        guard let bundle = Bundle(path: "/System/Library/PrivateFrameworks/MediaRemote.framework"),
              bundle.load() else {
            return nil
        }
        guard let cls = NSClassFromString("MRNowPlayingRequest") else { return nil }
        let clsObject = cls as AnyObject

        let playerPathSelector = Selector(("localNowPlayingPlayerPath"))
        let itemSelector = Selector(("localNowPlayingItem"))
        let infoSelector = Selector(("nowPlayingInfo"))
        let clientSelector = Selector(("client"))
        let displayNameSelector = Selector(("displayName"))

        var appName: String?
        if clsObject.responds(to: playerPathSelector),
           let playerPath = clsObject.perform(playerPathSelector)?.takeUnretainedValue() as? NSObject,
           playerPath.responds(to: clientSelector),
           let client = playerPath.perform(clientSelector)?.takeUnretainedValue() as? NSObject,
           client.responds(to: displayNameSelector),
           let name = client.perform(displayNameSelector)?.takeUnretainedValue() as? String {
            appName = name
        }

        guard clsObject.responds(to: itemSelector),
              let item = clsObject.perform(itemSelector)?.takeUnretainedValue() as? NSObject,
              item.responds(to: infoSelector),
              let infoDict = item.perform(infoSelector)?.takeUnretainedValue() as? NSDictionary else {
            return nil
        }

        guard let title = infoDict["kMRMediaRemoteNowPlayingInfoTitle"] as? String else {
            return nil
        }
        let artist = infoDict["kMRMediaRemoteNowPlayingInfoArtist"] as? String
        let album = infoDict["kMRMediaRemoteNowPlayingInfoAlbum"] as? String
        let playbackRate = infoDict["kMRMediaRemoteNowPlayingInfoPlaybackRate"] as? Double
        let isPlaying = playbackRate.map { $0 > 0 }

        return NowPlayingInfo(title: title, artist: artist, album: album, appName: appName, isPlaying: isPlaying)
    }
}
