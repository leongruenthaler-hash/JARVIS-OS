import SwiftUI

struct LicensesView: View {
    private let entries: [LicenseModelEntry] = [
        LicenseModelEntry(
            id: "phi4-mini",
            title: "phi4-mini",
            licenseType: "MIT License",
            summary: "Sehr freizügig – Nutzung, Kopieren, Weitergabe und Verkauf erlaubt, solange Copyright-Hinweis und Lizenztext beiliegen.",
            symbol: "bolt.fill",
            documents: [
                LicenseDocument(id: "phi4-mini-license", title: "MIT License", resourceSubdirectory: "Licenses/phi4-mini", resourceName: "LICENSE")
            ]
        ),
        LicenseModelEntry(
            id: "gemma3-4b",
            title: "gemma3:4b",
            licenseType: "Gemma Terms of Use",
            summary: "Googles eigenes Lizenzwerk – Nutzung und Weitergabe erlaubt, aber an eine Prohibited Use Policy gebunden.",
            symbol: "sparkles",
            documents: [
                LicenseDocument(id: "gemma-notice", title: "Notice", resourceSubdirectory: "Licenses/gemma3-4b", resourceName: "NOTICE"),
                LicenseDocument(id: "gemma-terms", title: "Terms of Use", resourceSubdirectory: "Licenses/gemma3-4b", resourceName: "TERMS_OF_USE"),
                LicenseDocument(id: "gemma-prohibited", title: "Prohibited Use", resourceSubdirectory: "Licenses/gemma3-4b", resourceName: "PROHIBITED_USE_POLICY")
            ]
        ),
        LicenseModelEntry(
            id: "qwen3-4b",
            title: "qwen3:4b",
            licenseType: "Apache License 2.0",
            summary: "Freizügige Open-Source-Lizenz von Alibaba Cloud – Weitergabe erlaubt, Lizenztext und Copyright-Hinweis müssen beiliegen.",
            symbol: "brain.head.profile",
            documents: [
                LicenseDocument(id: "qwen3-4b-license", title: "Apache License 2.0", resourceSubdirectory: "Licenses/qwen3-4b", resourceName: "LICENSE")
            ]
        ),
        LicenseModelEntry(
            id: "open-meteo",
            title: "Open-Meteo Wetterdaten",
            licenseType: "CC BY 4.0",
            summary: "Kostenlose Wetter- und Geokodierungsdaten für nicht-kommerzielle Nutzung – erfordert nur eine Namensnennung der Quelle.",
            symbol: "cloud.sun.fill",
            documents: [
                LicenseDocument(id: "open-meteo-attribution", title: "Attribution", resourceSubdirectory: "Licenses/open-meteo", resourceName: "ATTRIBUTION")
            ]
        )
    ]

    var body: some View {
        NavigationStack {
            List(entries) { entry in
                NavigationLink(value: entry) {
                    row(for: entry)
                }
            }
            .listStyle(.inset)
            .navigationTitle("Lizenzen")
            .navigationDestination(for: LicenseModelEntry.self) { entry in
                LicenseDetailView(entry: entry)
            }
        }
        .background(LiquidGlassBackground())
    }

    private func row(for entry: LicenseModelEntry) -> some View {
        HStack(spacing: 14) {
            Image(systemName: entry.symbol)
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(.indigo)
                .frame(width: 38, height: 38)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(entry.title)
                        .font(.headline)
                    Text(entry.licenseType)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.secondary.opacity(0.12), in: Capsule())
                }
                Text(entry.summary)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct LicenseModelEntry: Identifiable, Hashable {
    let id: String
    let title: String
    let licenseType: String
    let summary: String
    let symbol: String
    let documents: [LicenseDocument]

    static func == (lhs: LicenseModelEntry, rhs: LicenseModelEntry) -> Bool {
        lhs.id == rhs.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}

private struct LicenseDocument: Identifiable, Hashable {
    let id: String
    let title: String
    let resourceSubdirectory: String
    let resourceName: String
}

private struct LicenseDetailView: View {
    let entry: LicenseModelEntry
    @State private var selectedDocument: LicenseDocument

    init(entry: LicenseModelEntry) {
        self.entry = entry
        _selectedDocument = State(initialValue: entry.documents[0])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if entry.documents.count > 1 {
                Picker("Dokument", selection: $selectedDocument) {
                    ForEach(entry.documents) { document in
                        Text(document.title).tag(document)
                    }
                }
                .pickerStyle(.segmented)
                .padding(20)
            }

            ScrollView {
                Text(licenseText(for: selectedDocument))
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 32)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(LiquidGlassBackground())
        .navigationTitle(entry.title)
    }

    private func licenseText(for document: LicenseDocument) -> String {
        guard
            let url = Bundle.main.url(
                forResource: document.resourceName,
                withExtension: "txt",
                subdirectory: document.resourceSubdirectory
            ),
            let text = try? String(contentsOf: url, encoding: .utf8)
        else {
            return "Lizenztext konnte nicht geladen werden (\(document.resourceSubdirectory)/\(document.resourceName).txt fehlt im Bundle)."
        }
        return text
    }
}
