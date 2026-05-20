import AppKit

/// Узкая 3px-полоса по бокам виджета: при наведении курсор становится `openHand`,
/// клик+drag — перемещает всё окно через `NSWindow.performDrag(with:)`.
///
/// `addCursorRect` — стандартный AppKit-механизм, не требует ручного отслеживания
/// входа/выхода.
final class DragHandleView: NSView {
    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        // Прозрачный, но не пропускает hit-test (NSView default).
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func resetCursorRects() {
        super.resetCursorRects()
        addCursorRect(bounds, cursor: .openHand)
    }

    override func mouseDown(with event: NSEvent) {
        window?.performDrag(with: event)
    }
}
