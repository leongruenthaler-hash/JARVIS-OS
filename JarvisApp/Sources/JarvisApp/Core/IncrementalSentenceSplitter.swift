import Foundation

/// Detects complete sentences in text that arrives incrementally (streaming chat chunks),
/// so a caller can start speaking each sentence as soon as it's ready instead of waiting
/// for the full answer.
struct IncrementalSentenceSplitter {
    private var buffer = ""

    /// Feeds a newly-arrived chunk of streamed text. Returns any sentences that are now
    /// complete (end in `. ! ?` followed by whitespace), leaving any trailing incomplete
    /// fragment buffered for the next call - so a mid-sentence chunk boundary never splits
    /// a sentence early.
    mutating func feed(_ chunk: String) -> [String] {
        guard !chunk.isEmpty else { return [] }
        buffer += chunk

        var sentences: [String] = []
        while let range = buffer.range(of: #"[.!?]+[\"'”’)]?\s+"#, options: .regularExpression) {
            let sentence = String(buffer[..<range.upperBound]).trimmingCharacters(in: .whitespacesAndNewlines)
            buffer.removeSubrange(buffer.startIndex..<range.upperBound)
            if !sentence.isEmpty {
                sentences.append(sentence)
            }
        }
        return sentences
    }

    /// Call once the source stream is fully done. Returns whatever text is left in the
    /// buffer (e.g. the answer's final sentence, which may not end in punctuation) as one
    /// last piece, or `nil` if nothing remains.
    mutating func flush() -> String? {
        let remaining = buffer.trimmingCharacters(in: .whitespacesAndNewlines)
        buffer = ""
        return remaining.isEmpty ? nil : remaining
    }
}
