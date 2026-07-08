import SwiftUI

struct MainShellView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.jarvisTheme) private var theme

    private let assistantSections: [JarvisSection] = [.home, .actions, .chat, .history]
    private let workspaceSections: [JarvisSection] = [.mail, .calendar, .reminders, .files, .photos]
    private let systemSections: [JarvisSection] = [.privacy, .models, .settings]

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(min: 220, ideal: 250, max: 310)
        } detail: {
            detailView
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(LiquidGlassBackground())
        }
        .navigationSplitViewStyle(.balanced)
    }

    private var sidebar: some View {
        List(selection: $appState.selectedSection) {
            Section("Assistenz") {
                sectionRows(assistantSections)
            }

            Section("Arbeitsbereiche") {
                sectionRows(workspaceSections)
            }

            Section("System") {
                sectionRows(systemSections)
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("Jarvis")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await appState.refreshStatus(includeScanStates: true) }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Status aktualisieren")
            }
        }
        .safeAreaInset(edge: .bottom) {
            ServerStatusCard()
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
        }
        .background {
            if theme.isFuturistic {
                JarvisFuturisticBackground()
            }
        }
    }

    private func sectionRows(_ sections: [JarvisSection]) -> some View {
        ForEach(sections) { section in
            Label(section.rawValue, systemImage: section.symbol)
                .tag(section)
        }
    }

    @ViewBuilder
    private var detailView: some View {
        switch appState.selectedSection {
        case .home:
            HomeView()
        case .actions:
            ActionCenterView()
        case .chat:
            ChatView()
        case .mail:
            MailView()
        case .files:
            FilesView()
        case .photos:
            PhotosView()
        case .calendar:
            CalendarWorkspaceView()
        case .reminders:
            RemindersWorkspaceView()
        case .privacy:
            PrivacyView()
        case .models:
            ModelsView()
        case .settings:
            SettingsView()
        default:
            FeaturePlaceholderView(section: appState.selectedSection)
        }
    }
}
