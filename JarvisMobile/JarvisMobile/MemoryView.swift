import SwiftUI
import SceneKit

/// Echte, frei drehbare 3D-Speicher-Kugel (2026-09-11, vierte Version): jeder Punkt ist
/// jetzt ein ECHTER Eintrag von Jarvis' Speicher-Proxy (scripts/memory_proxy_server.py) -
/// OpenClaws eigene USER.md (Nutzer-Direktiven), MEMORY.md (kuratierte Langzeitfakten,
/// anfangs evtl. leer) UND, neu, jeder installierte Skill als eigener "Faehigkeit"-Punkt.
/// Vorherige Version fragte Jarvis per Chat, seine MEMORY.md als Freitext aufzulisten,
/// und riet die Kategorie pro Zeile anhand von Stichwoertern - zeigte dadurch nie
/// USER.md oder Jarvis' eigenes Werkzeug-Wissen, genau die Luecke, die hier geschlossen
/// wird. Kategorien kommen jetzt direkt vom Proxy (echt, kein Rateschema mehr), und es
/// gibt keine festen Deko-Basispunkte mehr - die Kugel zeigt nur noch, was wirklich da
/// ist, und waechst dadurch ehrlich mit jeder neuen echten Erinnerung/jedem neuen Skill.
struct MemoryView: View {
    fileprivate struct Category {
        let name: String
        let color: Color
    }

    fileprivate static let categories: [Category] = [
        Category(name: "Profil", color: .blue),
        Category(name: "Langzeit", color: .green),
        Category(name: "Fähigkeiten", color: .mint),
    ]
    fileprivate static let generalColor = Color.white

    fileprivate struct MemoryPoint {
        let content: String
        let category: String
    }

    private struct MemoryProxyFact: Decodable {
        let content: String
        let category: String
    }

    private struct MemoryProxyFactsResponse: Decodable {
        let facts: [MemoryProxyFact]
    }

    /// "Was Jarvis im Hintergrund macht" (2026-09-11) - die zuletzt gelaufenen echten
    /// OpenClaw-Automationen (Mail-/Kalender-Checks etc.), vom selben Speicher-Proxy wie
    /// die Kugel-Fakten. Kein Live-Stream laufender Werkzeug-Aufrufe (siehe
    /// scripts/memory_proxy_server.py::recent_activity() fuer die Begruendung).
    private struct MemoryProxyActivityEvent: Decodable, Identifiable {
        let label: String
        let reference: String?
        let at: TimeInterval
        var id: String { "\(label)-\(at)" }
    }

    private struct MemoryProxyActivityResponse: Decodable {
        let events: [MemoryProxyActivityEvent]
    }

    @State private var memoryItems: [MemoryPoint] = []
    @State private var isLoadingMemory = true
    @State private var memoryError: String?
    @State private var activityEvents: [MemoryProxyActivityEvent] = []

    @State private var testMessage = "Was liegt heute an?"
    @State private var isProcessing = false
    @State private var lastResponse: String?
    @State private var errorMessage: String?
    @State private var pulseTrigger = 0
    @FocusState private var inputFocused: Bool

    var body: some View {
        ZStack {
            if isLoadingMemory {
                ProgressView("Lade Erinnerungen von Jarvis...")
                    .tint(JarvisTheme.accent)
                    .foregroundStyle(.white)
            } else {
                SphereView(items: memoryItems, pulseTrigger: pulseTrigger)
                    .ignoresSafeArea()
                    .id(memoryItems.count)
            }

            VStack {
                legend
                if let memoryError {
                    Text(memoryError).font(.caption).foregroundStyle(.orange).padding(.top, 4)
                }
                activityPanel
                Spacer()
                bottomPanel
            }
        }
        .background(JarvisBackground())
        .navigationTitle("Speicher (\(memoryItems.count))")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task {
                        await loadMemory()
                        await loadActivity()
                    }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(isLoadingMemory)
            }
        }
        .task {
            await loadMemory()
            await loadActivity()
        }
        .onChange(of: isProcessing) { _, processing in
            if processing { pulseTrigger += 1 }
        }
    }

    @ViewBuilder
    private var activityPanel: some View {
        if !activityEvents.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(activityEvents.prefix(6)) { event in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(event.label)
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.white)
                                .lineLimit(1)
                            if let reference = event.reference, !reference.isEmpty {
                                Text(reference)
                                    .font(.system(size: 9))
                                    .foregroundStyle(JarvisTheme.textSecondary)
                                    .lineLimit(1)
                            }
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .frame(maxWidth: 160, alignment: .leading)
                        .background(JarvisTheme.cardFill, in: RoundedRectangle(cornerRadius: 10))
                    }
                }
                .padding(.horizontal, 12)
            }
            .padding(.top, 6)
        }
    }

    private func loadActivity() async {
        do {
            guard let baseURL = RemoteSettings.memoryBaseURL, let token = RemoteSettings.memoryToken else { return }
            var request = URLRequest(url: baseURL.appendingPathComponent("/api/memory/activity"))
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            let (data, _) = try await URLSession.shared.data(for: request)
            let response = try JSONDecoder().decode(MemoryProxyActivityResponse.self, from: data)
            activityEvents = response.events
        } catch {
            // Stumm fehlschlagen - die Aktivitaets-Leiste ist ein Zusatz, kein
            // kritischer Teil der Ansicht.
        }
    }

    private var legend: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                ForEach(Self.categories, id: \.name) { category in
                    HStack(spacing: 5) {
                        Circle().fill(category.color).frame(width: 8, height: 8)
                        Text(category.name)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(JarvisTheme.textSecondary)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(JarvisTheme.cardFill, in: Capsule())
                }
            }
            .padding(.horizontal, 12)
        }
        .padding(.top, 8)
    }

    private var bottomPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let lastResponse {
                Text(lastResponse)
                    .font(.callout)
                    .foregroundStyle(.white)
                    .padding(12)
                    .background(JarvisTheme.cardFill, in: RoundedRectangle(cornerRadius: 12))
                    .frame(maxHeight: 140)
            }
            if let errorMessage {
                Text(errorMessage).font(.caption).foregroundStyle(.red)
            }
            HStack(spacing: 8) {
                TextField("Testfrage an Jarvis", text: $testMessage, axis: .vertical)
                    .focused($inputFocused)
                    .foregroundStyle(.white)
                    .lineLimit(1...3)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(JarvisTheme.cardFill, in: RoundedRectangle(cornerRadius: 14))
                Button {
                    Task { await sendTest() }
                } label: {
                    Image(systemName: isProcessing ? "hourglass" : "paperplane.fill")
                        .font(.system(size: 16))
                        .frame(width: 36, height: 36)
                        .background(JarvisTheme.accentGradient, in: Circle())
                        .foregroundStyle(.black)
                }
                .disabled(isProcessing || testMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(12)
        .background(.ultraThinMaterial)
    }

    private func sendTest() async {
        inputFocused = false
        isProcessing = true
        errorMessage = nil
        defer { isProcessing = false }
        do {
            let response = try await APIClient().sendChat(testMessage, history: [])
            lastResponse = response.answer
            // Die Testfrage koennte selbst eine neue Erinnerung erzeugt
            // haben - Kugel nach der Antwort automatisch neu laden.
            await loadMemory()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadMemory() async {
        isLoadingMemory = memoryItems.isEmpty
        memoryError = nil
        do {
            guard let baseURL = RemoteSettings.memoryBaseURL, let token = RemoteSettings.memoryToken else {
                throw PairingError.notPaired
            }
            var request = URLRequest(url: baseURL.appendingPathComponent("/api/memory/facts"))
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            let (data, _) = try await URLSession.shared.data(for: request)
            let response = try JSONDecoder().decode(MemoryProxyFactsResponse.self, from: data)
            memoryItems = response.facts.map { MemoryPoint(content: $0.content, category: $0.category) }
        } catch {
            memoryError = "Konnte Erinnerungen nicht laden: \(error.localizedDescription)"
        }
        isLoadingMemory = false
    }

    fileprivate static func categoryIndex(_ name: String) -> Int? {
        categories.firstIndex(where: { $0.name == name })
    }
}

/// UIKit/SceneKit-Bruecke - SCNView bringt `allowsCameraControl` bereits
/// fertig mit (Ein-Finger-Drehen, Zwei-Finger-Zoom/Pan um die Kugel), das
/// spart eine eigene Touch-zu-Quaternion-Rotationslogik.
private struct SphereView: UIViewRepresentable {
    let items: [MemoryView.MemoryPoint]
    let pulseTrigger: Int

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = SphereView.buildScene(items: items)
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = false
        view.backgroundColor = .clear
        view.antialiasingMode = .multisampling4X
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {
        guard pulseTrigger > 0, let sphereNode = uiView.scene?.rootNode.childNode(withName: "core", recursively: false) else { return }
        let up = SCNAction.scale(to: 1.06, duration: 0.35)
        let down = SCNAction.scale(to: 1.0, duration: 0.45)
        up.timingMode = .easeOut
        down.timingMode = .easeInEaseOut
        sphereNode.runAction(.sequence([up, down]))
    }

    static func buildScene(items: [MemoryView.MemoryPoint]) -> SCNScene {
        let scene = SCNScene()

        let cameraNode = SCNNode()
        let camera = SCNCamera()
        camera.zFar = 30
        camera.wantsHDR = true
        camera.bloomIntensity = 1.6
        camera.bloomThreshold = 0.15
        camera.bloomBlurRadius = 16
        cameraNode.camera = camera
        cameraNode.position = SCNVector3(0, 0, 5.5)
        scene.rootNode.addChildNode(cameraNode)

        let coreNode = SCNNode()
        coreNode.name = "core"
        scene.rootNode.addChildNode(coreNode)

        let radius: CGFloat = 1.7
        var positions: [SCNVector3] = []
        var colors: [UIColor] = []

        func addPoint(theta: Double, phi: Double, color: UIColor) {
            let r = radius * CGFloat.random(in: 0.75...1.0)
            let x = r * CGFloat(sin(phi) * cos(theta))
            let y = r * CGFloat(cos(phi))
            let z = r * CGFloat(sin(phi) * sin(theta))
            positions.append(SCNVector3(x, y, z))
            colors.append(color)
        }

        // Ein Punkt pro ECHTEM Speicher-Fakt (Profil/Langzeit/Faehigkeiten, vom
        // Speicher-Proxy geliefert) - keine Deko-Basispunkte mehr (2026-09-11):
        // die Kugel zeigt jetzt ehrlich nur, was wirklich da ist, und waechst
        // dadurch tatsaechlich mit jeder neuen echten Erinnerung/jedem neuen Skill,
        // statt eine feste Anzahl vorzutaeuschen.
        for item in items {
            let color = MemoryView.categoryIndex(item.category).map { UIColor(MemoryView.categories[$0].color) } ?? UIColor(MemoryView.generalColor)
            addPoint(theta: Double.random(in: 0...(2 * .pi)), phi: Double.random(in: 0.05...(.pi - 0.05)), color: color)
        }

        for (position, color) in zip(positions, colors) {
            let geometry = SCNSphere(radius: CGFloat.random(in: 0.014...0.032))
            geometry.segmentCount = 8
            let material = SCNMaterial()
            material.diffuse.contents = UIColor.black
            material.emission.contents = color
            material.lightingModel = .constant
            geometry.firstMaterial = material
            let node = SCNNode(geometry: geometry)
            node.position = position
            coreNode.addChildNode(node)
        }

        if let lineNode = buildConnections(positions: positions) {
            coreNode.addChildNode(lineNode)
        }

        let rotation = SCNAction.repeatForever(SCNAction.rotateBy(x: 0, y: .pi * 2, z: 0, duration: 90))
        coreNode.runAction(rotation)

        return scene
    }

    /// Duenne, selbstleuchtende Linien zwischen nah beieinanderliegenden
    /// Punkten (bis zu 3 pro Punkt) - ein Draw-Call fuer alle Linien
    /// (SCNGeometryElement mit .line-Primitiven) statt hunderter einzelner
    /// Zylinder-Knoten.
    private static func buildConnections(positions: [SCNVector3]) -> SCNNode? {
        guard positions.count > 1 else { return nil }
        var vertices: [SCNVector3] = []
        let maxDistance: Float = 0.5

        for i in 0..<positions.count {
            var linked = 0
            for j in (i + 1)..<positions.count {
                let dx = positions[i].x - positions[j].x
                let dy = positions[i].y - positions[j].y
                let dz = positions[i].z - positions[j].z
                let distance = sqrtf(dx * dx + dy * dy + dz * dz)
                if distance < maxDistance {
                    vertices.append(positions[i])
                    vertices.append(positions[j])
                    linked += 1
                    if linked >= 3 { break }
                }
            }
        }
        guard !vertices.isEmpty else { return nil }

        let indices: [Int32] = Array(0..<Int32(vertices.count))
        let source = SCNGeometrySource(vertices: vertices)
        let element = SCNGeometryElement(indices: indices, primitiveType: .line)
        let geometry = SCNGeometry(sources: [source], elements: [element])
        let material = SCNMaterial()
        material.diffuse.contents = UIColor(red: 0.45, green: 0.82, blue: 0.92, alpha: 0.5)
        material.emission.contents = UIColor(red: 0.35, green: 0.75, blue: 0.88, alpha: 1)
        material.lightingModel = .constant
        geometry.firstMaterial = material
        return SCNNode(geometry: geometry)
    }
}

#Preview {
    NavigationStack { MemoryView() }
}
