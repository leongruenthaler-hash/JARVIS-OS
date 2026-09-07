import SwiftUI

/// Placeholder after the OpenClaw migration (2026-09-06): the old Jarvis
/// backend exposed a pull-based /api/proactivity/events API that this tab
/// polled. OpenClaw's proactivity model works differently (push via
/// channels/cron + daily briefings, no matching pull endpoint), so this view
/// is parked here rather than deleted outright - kept out of RootView's
/// TabView until a channel-based equivalent is wired up.
struct ProactivityView: View {
    var body: some View {
        ContentUnavailableView(
            "Hinweise laufen jetzt über OpenClaw",
            systemImage: "bell.badge",
            description: Text("Proaktive Hinweise kommen jetzt als Push über einen OpenClaw-Kanal (z. B. iMessage/Telegram), nicht mehr über diese Ansicht.")
        )
    }
}

#Preview {
    NavigationStack { ProactivityView() }
}
