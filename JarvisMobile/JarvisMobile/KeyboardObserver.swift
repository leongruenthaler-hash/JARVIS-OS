import SwiftUI
import UIKit
import Combine

/// Tracks the on-screen keyboard height via NotificationCenter instead of
/// relying on SwiftUI's implicit safe-area keyboard avoidance - needed
/// because ChatView's input bar kept disappearing behind the keyboard
/// (live-reported bug 2026-09-07) even with .safeAreaInset(edge: .bottom),
/// most likely due to the TabView > NavigationStack > ChatView nesting
/// interfering with automatic keyboard-safe-area propagation. Explicit
/// notification tracking sidesteps that entirely.
///
/// Overlap is computed against the CALLING VIEW's own bottom edge
/// (`viewMaxY`, set by ChatView via a GeometryReader), not the raw window
/// height - using window height double-counted the tab bar's height (round
/// two of the same bug, 2026-09-07): TabView content already excludes the
/// tab bar from its own frame, so subtracting the keyboard's absolute
/// screen position from the FULL window height re-added that same space a
/// second time, producing an oversized gap once the tab-bar-relative fix
/// for "hidden behind keyboard" landed.
@MainActor
final class KeyboardObserver: ObservableObject {
    @Published private(set) var height: CGFloat = 0
    /// Bottom Y of the observing view in global/window coordinates - set by
    /// that view via a GeometryReader so the overlap math below matches
    /// whatever chrome (tab bar, nav bar) is actually already excluded from
    /// its frame, instead of assuming the full window height.
    var viewMaxY: CGFloat = 0

    private var cancellables = Set<AnyCancellable>()

    init() {
        NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)
            .sink { [weak self] notification in
                guard let self,
                      let frame = notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect
                else { return }
                let reference = self.viewMaxY > 0 ? self.viewMaxY : frame.origin.y
                self.height = max(0, reference - frame.origin.y)
            }
            .store(in: &cancellables)

        NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)
            .sink { [weak self] _ in self?.height = 0 }
            .store(in: &cancellables)
    }
}
