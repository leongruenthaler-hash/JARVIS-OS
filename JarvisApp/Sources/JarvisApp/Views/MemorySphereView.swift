import SwiftUI
import SceneKit

/// Direkter Port von JarvisMobile/MemoryView.swift's SphereView (2026-09-11, auf
/// ausdruecklichen Wunsch: "das Design von der Mobile App auch auf die Mac App
/// uebertragen, die sieht jetzt wenigstens mal gut aus") - ersetzt die vorherige
/// MemoryCoreView (2D-Canvas-Ringe). Gleiche 3D-Kugel, gleiche Kategorie-Farben
/// (Profil/Langzeit/Faehigkeiten), gleiche "keine Deko-Basispunkte"-Haltung: jeder
/// Punkt ist ein echter Fakt vom Speicher-Proxy. Einziger Unterschied zur Mobile-
/// Version: hier per Klick antippbar (macOS-Interaktionsmodell), damit Bestaetigen/
/// Ablehnen/Loeschen (siehe MemoryView.swift's factDetailSheet) erhalten bleibt.
struct MemorySphereView: View {
    let facts: [MemoryFact]
    let onSelect: (MemoryFact) -> Void

    var body: some View {
        SceneKitSphereView(facts: facts, onSelect: onSelect)
            .overlay(alignment: .bottom) { legend }
            .overlay {
                if facts.isEmpty {
                    Text("Noch keine Erinnerungen gespeichert.")
                        .foregroundStyle(.secondary)
                        .padding(.top, 90)
                }
            }
    }

    private var legend: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                ForEach(MemorySphereCategory.all, id: \.name) { category in
                    HStack(spacing: 5) {
                        Circle().fill(category.color).frame(width: 8, height: 8)
                        Text(category.name)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(.thinMaterial, in: Capsule())
                }
            }
            .padding(.horizontal, 12)
        }
        .padding(.bottom, 12)
    }
}

struct MemorySphereCategory {
    let name: String
    let color: Color

    static let all: [MemorySphereCategory] = [
        MemorySphereCategory(name: "Profil", color: .blue),
        MemorySphereCategory(name: "Langzeit", color: .green),
        MemorySphereCategory(name: "Fähigkeiten", color: .mint),
    ]
    static let generalColor = Color.white

    static func index(for name: String) -> Int? {
        all.firstIndex(where: { $0.name == name })
    }
}

private struct SceneKitSphereView: NSViewRepresentable {
    let facts: [MemoryFact]
    let onSelect: (MemoryFact) -> Void

    func makeNSView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = SceneKitSphereView.buildScene(facts: facts)
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = false
        view.backgroundColor = .clear
        view.antialiasingMode = .multisampling4X
        let click = NSClickGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.handleClick(_:)))
        view.addGestureRecognizer(click)
        context.coordinator.view = view
        context.coordinator.resolveTap = { factID in
            guard let fact = facts.first(where: { $0.id == factID }) else { return }
            onSelect(fact)
        }
        return view
    }

    func updateNSView(_ nsView: SCNView, context: Context) {
        context.coordinator.resolveTap = { factID in
            guard let fact = facts.first(where: { $0.id == factID }) else { return }
            onSelect(fact)
        }
        // Facts-Identitaet (Anzahl+Inhalt) hat sich geaendert - Szene neu aufbauen.
        nsView.scene = SceneKitSphereView.buildScene(facts: facts)
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject {
        weak var view: SCNView?
        var resolveTap: ((String) -> Void)?

        @objc func handleClick(_ recognizer: NSClickGestureRecognizer) {
            guard let view else { return }
            let point = recognizer.location(in: view)
            let hits = view.hitTest(point, options: [.searchMode: SCNHitTestSearchMode.closest.rawValue])
            guard let node = hits.first?.node, let factID = node.name else { return }
            resolveTap?(factID)
        }
    }

    static func buildScene(facts: [MemoryFact]) -> SCNScene {
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
        var colors: [NSColor] = []
        var factIDs: [String] = []

        func addPoint(theta: Double, phi: Double, color: NSColor) {
            let r = radius * CGFloat.random(in: 0.75...1.0)
            let x = r * CGFloat(sin(phi) * cos(theta))
            let y = r * CGFloat(cos(phi))
            let z = r * CGFloat(sin(phi) * sin(theta))
            positions.append(SCNVector3(x, y, z))
            colors.append(color)
        }

        for fact in facts {
            let color = MemorySphereCategory.index(for: fact.category).map { NSColor(MemorySphereCategory.all[$0].color) } ?? NSColor(MemorySphereCategory.generalColor)
            addPoint(theta: Double.random(in: 0...(2 * .pi)), phi: Double.random(in: 0.05...(.pi - 0.05)), color: color)
            factIDs.append(fact.id)
        }

        for index in positions.indices {
            let geometry = SCNSphere(radius: CGFloat.random(in: 0.014...0.032))
            geometry.segmentCount = 8
            let material = SCNMaterial()
            material.diffuse.contents = NSColor.black
            material.emission.contents = colors[index]
            material.lightingModel = .constant
            geometry.firstMaterial = material
            let node = SCNNode(geometry: geometry)
            node.position = positions[index]
            node.name = factIDs[index]
            coreNode.addChildNode(node)
        }

        if let lineNode = buildConnections(positions: positions) {
            coreNode.addChildNode(lineNode)
        }

        let rotation = SCNAction.repeatForever(SCNAction.rotateBy(x: 0, y: .pi * 2, z: 0, duration: 90))
        coreNode.runAction(rotation)

        return scene
    }

    private static func buildConnections(positions: [SCNVector3]) -> SCNNode? {
        guard positions.count > 1 else { return nil }
        var vertices: [SCNVector3] = []
        let maxDistance: Float = 0.5

        for i in 0..<positions.count {
            var linked = 0
            for j in (i + 1)..<positions.count {
                let dx = Float(positions[i].x) - Float(positions[j].x)
                let dy = Float(positions[i].y) - Float(positions[j].y)
                let dz = Float(positions[i].z) - Float(positions[j].z)
                let dxSquared = dx * dx
                let dySquared = dy * dy
                let dzSquared = dz * dz
                let sumOfSquares = dxSquared + dySquared + dzSquared
                let distance = sqrtf(sumOfSquares)
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
        material.diffuse.contents = NSColor(red: 0.45, green: 0.82, blue: 0.92, alpha: 0.5)
        material.emission.contents = NSColor(red: 0.35, green: 0.75, blue: 0.88, alpha: 1)
        material.lightingModel = .constant
        geometry.firstMaterial = material
        return SCNNode(geometry: geometry)
    }
}
