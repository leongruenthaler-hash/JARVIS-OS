import CoreGraphics
import Foundation

/// Pure positioning logic for MemoryCoreView (no SwiftUI import) - kept separate so the
/// math is testable independent of rendering. Coordinates are normalized (0...1 relative
/// to a unit square centered on (0.5, 0.5)); the view scales them to its own canvas size.
struct MemoryCoreNode: Identifiable, Equatable {
    let id: String
    let category: String
    let position: CGPoint
    let ringIndex: Int
}

struct MemoryCoreRing: Identifiable, Equatable {
    var id: String { category }
    let category: String
    let ringIndex: Int
    let radius: Double
}

struct MemoryCoreLayout: Equatable {
    let rings: [MemoryCoreRing]
    let nodes: [MemoryCoreNode]

    static let empty = MemoryCoreLayout(rings: [], nodes: [])

    /// Largest category closest to the core (ringIndex 0) - see plan's open question,
    /// resolved as "count-based" since it needs no per-category configuration.
    static func compute(facts: [MemoryFact]) -> MemoryCoreLayout {
        guard !facts.isEmpty else { return .empty }

        let grouped = Dictionary(grouping: facts, by: \.category)
        let orderedCategories = grouped.keys.sorted { lhs, rhs in
            let lhsCount = grouped[lhs]?.count ?? 0
            let rhsCount = grouped[rhs]?.count ?? 0
            if lhsCount != rhsCount { return lhsCount > rhsCount }
            return lhs < rhs
        }

        let baseRadius = 0.14
        let ringSpacing = 0.09
        let maxRadius = 0.46

        var rings: [MemoryCoreRing] = []
        var nodes: [MemoryCoreNode] = []

        for (index, category) in orderedCategories.enumerated() {
            let radius = min(baseRadius + Double(index) * ringSpacing, maxRadius)
            rings.append(MemoryCoreRing(category: category, ringIndex: index, radius: radius))

            let factsInCategory = grouped[category] ?? []
            let count = factsInCategory.count
            for (position, fact) in factsInCategory.enumerated() {
                let evenAngle = count > 0 ? (2 * Double.pi * Double(position) / Double(count)) : 0
                let jitter = deterministicJitter(for: fact.id)
                let angle = evenAngle + jitter
                let point = CGPoint(
                    x: 0.5 + radius * cos(angle),
                    y: 0.5 + radius * sin(angle)
                )
                nodes.append(MemoryCoreNode(id: fact.id, category: category, position: point, ringIndex: index))
            }
        }

        return MemoryCoreLayout(rings: rings, nodes: nodes)
    }

    /// Small, stable per-fact angular offset derived from the fact id - NOT
    /// Double.random, so the layout doesn't visibly reshuffle between refreshes as long
    /// as the same facts are present (see plan's Design-Entscheidung on this point).
    private static func deterministicJitter(for id: String) -> Double {
        let hash = id.unicodeScalars.reduce(UInt32(5381)) { partial, scalar in
            partial &* 33 &+ scalar.value
        }
        let normalized = Double(hash % 1000) / 1000.0
        return (normalized - 0.5) * 0.5
    }
}
