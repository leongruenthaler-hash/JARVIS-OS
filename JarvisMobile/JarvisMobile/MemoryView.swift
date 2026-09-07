import SwiftUI
import SceneKit

/// Echte, frei drehbare 3D-Speicher-Kugel (2026-09-07, dritte Version):
/// jeder Punkt ist jetzt ein ECHTER Eintrag aus Jarvis' MEMORY.md, nicht mehr
/// eine feste Platzhalter-Anzahl - wird bei jedem Oeffnen des Tabs frisch
/// abgefragt, damit neue Erinnerungen tatsaechlich als neue Punkte
/// erscheinen. OpenClaw speichert Erinnerungen als Fliesstext ohne
/// Kategorie-Metadaten, daher ist die Farb-Zuordnung pro Zeile eine
/// Stichwort-Schaetzung (siehe categorize()), kein zuverlaessiges
/// Kategoriesystem - Eintraege ohne erkanntes Stichwort werden neutral
/// (weiss) dargestellt statt falsch einsortiert.
struct MemoryView: View {
    fileprivate struct Category {
        let name: String
        let color: Color
        let keywords: [String]
        /// Feste "Faehigkeit ist vorhanden"-Basis-Punkte - unabhaengig von
        /// echten Erinnerungen, illustrativ (siehe Datei-Kommentar). Echte
        /// MEMORY.md-Eintraege kommen zusaetzlich obendrauf, ersetzen diese
        /// Basis nicht (live gewuenscht 2026-09-07: "beides zusammen").
        let baselinePoints: Int
    }

    fileprivate static let categories: [Category] = [
        Category(name: "Mail", color: .blue, keywords: ["mail", "email", "e-mail", "posteingang", "nachricht von"], baselinePoints: 22),
        Category(name: "Kalender", color: .orange, keywords: ["kalender", "termin", "meeting", "uhrzeit"], baselinePoints: 18),
        Category(name: "Kontakte", color: .purple, keywords: ["kontakt", "telefonnummer", "adresse von"], baselinePoints: 14),
        Category(name: "Notizen", color: .yellow, keywords: ["notiz"], baselinePoints: 20),
        Category(name: "Erinnerungen", color: .green, keywords: ["erinnerung", "reminder"], baselinePoints: 16),
        Category(name: "Kamera", color: .pink, keywords: ["foto", "kamera", "bild von"], baselinePoints: 8),
        Category(name: "Bildschirm", color: .teal, keywords: ["screenshot", "bildschirm"], baselinePoints: 8),
        Category(name: "Web-Suche", color: .indigo, keywords: ["such", "recherch", "internet"], baselinePoints: 12),
        Category(name: "Wetter", color: .cyan, keywords: ["wetter", "temperatur", "regen"], baselinePoints: 6),
        Category(name: "Aufgaben", color: .red, keywords: ["aufgabe", "projekt", "todo", "to-do"], baselinePoints: 18),
    ]
    fileprivate static let generalColor = Color.white

    @State private var memoryItems: [String] = []
    @State private var isLoadingMemory = true
    @State private var memoryError: String?

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
                    Task { await loadMemory() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(isLoadingMemory)
            }
        }
        .task { await loadMemory() }
        .onChange(of: isProcessing) { _, processing in
            if processing { pulseTrigger += 1 }
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
        let instruction = """
        Lies deine MEMORY.md und liste JEDEN Eintrag als eigene Zeile auf - keine Nummerierung, keine Überschriften, keine Markdown-Formatierung, keine Erklärung davor oder danach. Genau eine Erinnerung pro Zeile, so kurz wie im Original. Falls MEMORY.md leer ist oder nicht existiert, antworte NUR mit LEER.
        """
        do {
            let response = try await APIClient().sendChat(instruction, history: [])
            let lines = response.answer
                .split(whereSeparator: \.isNewline)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty && $0.uppercased() != "LEER" }
            memoryItems = lines
        } catch {
            memoryError = "Konnte Erinnerungen nicht laden: \(error.localizedDescription)"
        }
        isLoadingMemory = false
    }

    fileprivate static func categorize(_ text: String) -> Int? {
        let lower = text.lowercased()
        for (index, category) in categories.enumerated() {
            if category.keywords.contains(where: { lower.contains($0) }) {
                return index
            }
        }
        return nil
    }
}

/// UIKit/SceneKit-Bruecke - SCNView bringt `allowsCameraControl` bereits
/// fertig mit (Ein-Finger-Drehen, Zwei-Finger-Zoom/Pan um die Kugel), das
/// spart eine eigene Touch-zu-Quaternion-Rotationslogik.
private struct SphereView: UIViewRepresentable {
    let items: [String]
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

    static func buildScene(items: [String]) -> SCNScene {
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

        // Basis-Punkte: "diese Faehigkeit ist eingerichtet", ein eigener
        // Laengengrad-Sektor pro Kategorie - unabhaengig von echten
        // Erinnerungen, bleibt immer sichtbar (live gewuenscht 2026-09-07).
        for (index, category) in MemoryView.categories.enumerated() {
            let sliceStart = Double(index) / Double(MemoryView.categories.count) * 2 * .pi
            let sliceEnd = Double(index + 1) / Double(MemoryView.categories.count) * 2 * .pi
            let uiColor = UIColor(category.color)
            for _ in 0..<category.baselinePoints {
                addPoint(theta: Double.random(in: sliceStart...sliceEnd), phi: Double.random(in: 0.05...(.pi - 0.05)), color: uiColor)
            }
        }

        // ZUSAETZLICH ein Punkt pro ECHTEM MEMORY.md-Eintrag, frei verteilt
        // (nicht auf den Kategorie-Sektor beschraenkt) - waechst mit neuen
        // Erinnerungen. Ohne erkanntes Stichwort (siehe categorize()) neutral
        // weiss statt falsch einsortiert.
        for text in items {
            let color = MemoryView.categorize(text).map { UIColor(MemoryView.categories[$0].color) } ?? UIColor(MemoryView.generalColor)
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
