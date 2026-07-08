import SwiftUI

struct ScanProgressCard: View {
    let title: String
    let symbol: String
    let progress: ScanProgress
    var stats: [(String, String)] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label(title, systemImage: symbol)
                    .font(.headline)
                Spacer()
                Text(progress.status.label)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(statusColor.opacity(0.14), in: Capsule())
                    .foregroundStyle(statusColor)
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(progress.currentLabel.isEmpty ? "Bereit" : progress.currentLabel)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(progress.percentText)
                        .font(.callout.monospacedDigit().weight(.semibold))
                }
                ProgressView(value: progress.totalItems > 0 ? progress.fraction : nil)
                    .progressViewStyle(.linear)
            }

            if progress.totalItems > 0 {
                Text("\(progress.currentItem) von \(progress.totalItems)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            if !stats.isEmpty {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 10)], spacing: 10) {
                    ForEach(stats, id: \.0) { item in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.0)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(item.1.isEmpty ? "-" : item.1)
                                .font(.callout.weight(.semibold))
                                .lineLimit(2)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
                        )
                    }
                }
            }

            if let error = progress.errorMessage, !error.isEmpty {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding(18)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .strokeBorder(
                    LinearGradient(
                        colors: [Color.white.opacity(0.32), statusColor.opacity(0.22), Color.white.opacity(0.08)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
        )
        .shadow(color: statusColor.opacity(0.08), radius: 22, x: 0, y: 12)
        .shadow(color: Color.black.opacity(0.06), radius: 10, x: 0, y: 4)
    }

    private var statusColor: Color {
        switch progress.status {
        case .completed: .green
        case .failed: .red
        case .cancelled: .orange
        case .scanning, .indexing, .preparing: .blue
        case .idle: .secondary
        }
    }
}
