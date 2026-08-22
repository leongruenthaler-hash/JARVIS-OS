import SwiftUI

/// The Gedaechtnis-Kern-Ansicht (Phase F-Folgeschritt): a pulsing central core surrounded
/// by concentric per-category rings of confirmed facts, plus an outer, generic field
/// standing in for the much larger photos/files index - individual field points flare up
/// and get labelled only when a real access actually happens (AppState.recentActivity).
/// See plans/2026-08-07-jarvis-memory-neural-network-view.md for the design rationale -
/// this deliberately replaced an earlier flat "category islands" draft that read as an
/// org chart rather than a brain.
struct MemoryCoreView: View {
    let facts: [MemoryFact]
    let activityEvents: [ActivityEvent]
    let onSelect: (MemoryFact) -> Void

    @Environment(\.jarvisTheme) private var theme
    /// Graph-Zeichenfarbe war hart Color.cyan verdrahtet, unabhaengig vom Theme - jetzt
    /// wie der Rest der App auf die aktive Akzentfarbe umgestellt.
    private var accentColor: Color { theme.isDark ? theme.primaryAccent : .cyan }
    @State private var layout: MemoryCoreLayout = .empty
    private let pulseController = MemorySynapsePulseController()
    @State private var fieldPoints: [FieldPoint] = []
    @State private var fieldAssignments: [String: FieldPoint] = [:]
    /// Facts keyed by id, rebuilt only when `facts` changes (see rebuildLayout()) so that
    /// drawNodes()/pulseColor(), which run every animation frame, don't do an O(n) linear
    /// scan of `facts` per node (that was O(nodes * facts) per frame).
    @State private var factsByID: [String: MemoryFact] = [:]

    private struct FieldPoint: Identifiable, Equatable {
        let id: Int
        let angle: Double
        let radiusFactor: Double
        let size: Double
        let baseOpacity: Double
    }

    var body: some View {
        GeometryReader { proxy in
            let side = min(proxy.size.width, proxy.size.height)
            let origin = CGPoint(x: proxy.size.width / 2 - side / 2, y: proxy.size.height / 2 - side / 2)

            TimelineView(.animation) { context in
                Canvas { canvas, size in
                    draw(in: &canvas, size: size, date: context.date)
                }
                .onChange(of: context.date) { _, date in
                    pulseController.syncTriggeredPulses(facts: facts, now: date)
                    pulseController.syncActivityEvents(activityEvents, now: date)
                    pulseController.maybeFireBackgroundPulse(facts: facts, now: date)
                    pulseController.purgeFinished(now: date)
                }
            }
            .frame(width: side, height: side)
            .position(x: proxy.size.width / 2, y: proxy.size.height / 2)
            .overlay(labelsOverlay(canvasSide: side))
            .contentShape(Rectangle())
            .onTapGesture { location in
                handleTap(at: location, canvasOrigin: origin, side: side)
            }
        }
        .onAppear { rebuildLayout() }
        .onChange(of: facts) { _, _ in rebuildLayout() }
        .overlay {
            if facts.isEmpty {
                Text("Noch keine Erinnerungen gespeichert.")
                    .foregroundStyle(.secondary)
                    .padding(.top, 90)
            }
        }
    }

    private func rebuildLayout() {
        layout = MemoryCoreLayout.compute(facts: facts)
        factsByID = Dictionary(facts.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        if fieldPoints.isEmpty {
            fieldPoints = (0..<48).map { index in
                FieldPoint(
                    id: index,
                    angle: Double.random(in: 0..<(2 * .pi)),
                    radiusFactor: Double.random(in: 0.5...0.68),
                    size: Double.random(in: 1.4...2.6),
                    baseOpacity: Double.random(in: 0.14...0.32)
                )
            }
        }
    }

    // MARK: - Drawing

    private func draw(in canvas: inout GraphicsContext, size: CGSize, date: Date) {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let scale = min(size.width, size.height)
        let fieldFlares = activeFieldFlares(at: date)

        drawField(in: &canvas, center: center, scale: scale, flares: fieldFlares)
        drawRings(in: &canvas, center: center, scale: scale)
        drawSynapses(in: &canvas, center: center, scale: scale)
        drawPulses(in: &canvas, center: center, scale: scale, date: date)
        drawNodes(in: &canvas, center: center, scale: scale)
        drawCore(in: &canvas, center: center, scale: scale, date: date)
    }

    private func drawField(in canvas: inout GraphicsContext, center: CGPoint, scale: CGFloat, flares: [Int: Double]) {
        let dust = Color(red: 0.29, green: 0.49, blue: 0.57)
        for point in fieldPoints {
            let radius = point.radiusFactor * scale / 2
            let position = CGPoint(
                x: center.x + radius * cos(point.angle),
                y: center.y + radius * sin(point.angle)
            )
            let flare = flares[point.id] ?? 0
            let opacity = point.baseOpacity + flare * 0.65
            let radiusPx = point.size + flare * 3.5
            canvas.fill(
                Path(ellipseIn: CGRect(x: position.x - radiusPx, y: position.y - radiusPx, width: radiusPx * 2, height: radiusPx * 2)),
                with: .color(dust.opacity(opacity))
            )
        }
    }

    private func drawRings(in canvas: inout GraphicsContext, center: CGPoint, scale: CGFloat) {
        for ring in layout.rings {
            let radius = ring.radius * scale
            var path = Path()
            path.addEllipse(in: CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
            canvas.stroke(path, with: .color(accentColor.opacity(0.1)), lineWidth: 0.6)
        }
    }

    private func drawSynapses(in canvas: inout GraphicsContext, center: CGPoint, scale: CGFloat) {
        for node in layout.nodes {
            let point = CGPoint(x: center.x + (node.position.x - 0.5) * scale, y: center.y + (node.position.y - 0.5) * scale)
            var path = Path()
            path.move(to: center)
            path.addLine(to: point)
            canvas.stroke(path, with: .color(accentColor.opacity(0.14)), lineWidth: 0.6)
        }
    }

    private func drawPulses(in canvas: inout GraphicsContext, center: CGPoint, scale: CGFloat, date: Date) {
        for pulse in pulseController.activePulses {
            guard let target = targetPosition(for: pulse.target, center: center, scale: scale) else { continue }
            let progress = pulse.progress(at: date)
            let x = center.x + (target.x - center.x) * progress
            let y = center.y + (target.y - center.y) * progress
            let radius: CGFloat = 3.4
            let glowColor = pulseColor(for: pulse.target)
            canvas.fill(
                Path(ellipseIn: CGRect(x: x - radius * 2, y: y - radius * 2, width: radius * 4, height: radius * 4)),
                with: .color(glowColor.opacity(0.18))
            )
            canvas.fill(
                Path(ellipseIn: CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)),
                with: .color(glowColor)
            )
        }
    }

    private func drawNodes(in canvas: inout GraphicsContext, center: CGPoint, scale: CGFloat) {
        for node in layout.nodes {
            guard let fact = factsByID[node.id] else { continue }
            let point = CGPoint(x: center.x + (node.position.x - 0.5) * scale, y: center.y + (node.position.y - 0.5) * scale)
            let color = memorySensitivityColor(fact.sensitivity)
            let baseOpacity = memoryStatusOpacity(fact.status)
            let flare: CGFloat = nodeIsPulsing(node.id) ? 1.6 : 1.0
            let radius: CGFloat = 5 * flare

            canvas.fill(
                Path(ellipseIn: CGRect(x: point.x - radius * 2.4, y: point.y - radius * 2.4, width: radius * 4.8, height: radius * 4.8)),
                with: .color(color.opacity(0.14 * baseOpacity))
            )
            canvas.fill(
                Path(ellipseIn: CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2)),
                with: .color(color.opacity(baseOpacity))
            )
            if fact.status == "pending_confirmation" {
                let ringRadius = radius + 4
                var dashed = Path(ellipseIn: CGRect(x: point.x - ringRadius, y: point.y - ringRadius, width: ringRadius * 2, height: ringRadius * 2))
                dashed = dashed.strokedPath(StrokeStyle(lineWidth: 1, dash: [2, 3]))
                canvas.fill(dashed, with: .color(color.opacity(0.7)))
            }
        }
    }

    private func drawCore(in canvas: inout GraphicsContext, center: CGPoint, scale: CGFloat, date: Date) {
        let t = date.timeIntervalSinceReferenceDate
        let breathe = (sin(t * (2 * .pi / 1.5)) + 1) / 2

        let outerRadius = scale * (0.05 + breathe * 0.008)
        canvas.fill(
            Path(ellipseIn: CGRect(x: center.x - outerRadius, y: center.y - outerRadius, width: outerRadius * 2, height: outerRadius * 2)),
            with: .color(accentColor.opacity(0.06))
        )

        let midRadius = scale * (0.028 + breathe * 0.004)
        canvas.fill(
            Path(ellipseIn: CGRect(x: center.x - midRadius, y: center.y - midRadius, width: midRadius * 2, height: midRadius * 2)),
            with: .radialGradient(
                Gradient(colors: [.white, accentColor, accentColor.opacity(0)]),
                center: center,
                startRadius: 0,
                endRadius: midRadius
            )
        )

        let coreRadius = scale * 0.01
        canvas.fill(
            Path(ellipseIn: CGRect(x: center.x - coreRadius, y: center.y - coreRadius, width: coreRadius * 2, height: coreRadius * 2)),
            with: .color(.white)
        )
    }

    // MARK: - Pulse target resolution

    private func targetPosition(for target: PulseTarget, center: CGPoint, scale: CGFloat) -> CGPoint? {
        switch target {
        case .node(let factID):
            guard let node = layout.nodes.first(where: { $0.id == factID }) else { return nil }
            return CGPoint(x: center.x + (node.position.x - 0.5) * scale, y: center.y + (node.position.y - 0.5) * scale)
        case .field(let type, let label):
            let point = assignedFieldPoint(type: type, label: label)
            let radius = point.radiusFactor * scale / 2
            return CGPoint(x: center.x + radius * cos(point.angle), y: center.y + radius * sin(point.angle))
        }
    }

    /// Which field point (by id) each currently active field-type pulse is headed to,
    /// and how "arrived" it is (1 = just landed, fading immediately after) - computed
    /// once per frame from the pulses themselves (forward lookup) rather than having
    /// drawField() search pulses per field point (that reverse lookup previously made
    /// the type-checker choke on an over-nested expression).
    private func activeFieldFlares(at date: Date) -> [Int: Double] {
        var flares: [Int: Double] = [:]
        for pulse in pulseController.activePulses {
            guard case .field(let type, let label) = pulse.target else { continue }
            let point = assignedFieldPoint(type: type, label: label)
            flares[point.id] = max(flares[point.id] ?? 0, pulse.progress(at: date))
        }
        return flares
    }

    private func assignedFieldPoint(type: String, label: String) -> FieldPoint {
        let key = "\(type)-\(label)"
        if let existing = fieldAssignments[key] { return existing }
        let point = fieldPoints.randomElement() ?? FieldPoint(id: 0, angle: 0, radiusFactor: 0.55, size: 2, baseOpacity: 0.2)
        fieldAssignments[key] = point
        return point
    }

    private func pulseColor(for target: PulseTarget) -> Color {
        switch target {
        case .node(let factID):
            guard let fact = factsByID[factID] else { return .cyan }
            return memorySensitivityColor(fact.sensitivity)
        case .field:
            return .cyan
        }
    }

    private func nodeIsPulsing(_ factID: String) -> Bool {
        pulseController.activePulses.contains { pulse in
            if case .node(let id) = pulse.target { return id == factID }
            return false
        }
    }

    // MARK: - Labels (real SwiftUI text overlay - Canvas text is harder to keep crisp)

    private struct FieldLabelEntry {
        let key: String
        let label: String
        let position: CGPoint
    }

    @ViewBuilder
    private func labelsOverlay(canvasSide: CGFloat) -> some View {
        ZStack {
            ForEach(layout.rings) { ring in
                Text(ring.category.uppercased())
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(accentColor.opacity(0.5))
                    .position(x: canvasSide / 2, y: canvasSide / 2 - ring.radius * canvasSide + 10)
            }
            ForEach(activeFieldLabels(canvasSide: canvasSide), id: \.key) { entry in
                Text(entry.label)
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(accentColor)
                    .padding(.horizontal, 4)
                    .background(.black.opacity(0.4), in: RoundedRectangle(cornerRadius: 3))
                    .position(x: entry.position.x, y: entry.position.y - 12)
            }
        }
        .frame(width: canvasSide, height: canvasSide)
        .allowsHitTesting(false)
    }

    private func activeFieldLabels(canvasSide: CGFloat) -> [FieldLabelEntry] {
        pulseController.activePulses.compactMap { pulse in
            guard case .field(let type, let label) = pulse.target else { return nil }
            let point = assignedFieldPoint(type: type, label: label)
            let radius = point.radiusFactor * canvasSide / 2
            let position = CGPoint(
                x: canvasSide / 2 + radius * cos(point.angle),
                y: canvasSide / 2 + radius * sin(point.angle)
            )
            let prefix = type == "photo" ? "foto" : (type == "file" ? "datei" : type)
            return FieldLabelEntry(key: "\(type)-\(label)", label: "\(prefix) · \(label)", position: position)
        }
    }

    // MARK: - Tap handling

    private func handleTap(at location: CGPoint, canvasOrigin: CGPoint, side: CGFloat) {
        let local = CGPoint(x: location.x - canvasOrigin.x, y: location.y - canvasOrigin.y)
        let tolerance: CGFloat = 14
        for node in layout.nodes {
            let point = CGPoint(x: node.position.x * side, y: node.position.y * side)
            let distance = hypot(point.x - local.x, point.y - local.y)
            if distance <= tolerance, let fact = factsByID[node.id] {
                onSelect(fact)
                return
            }
        }
    }
}
