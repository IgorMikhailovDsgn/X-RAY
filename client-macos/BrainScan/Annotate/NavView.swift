import AppKit

/// Триггер выпадающего списка bbox одной сущности: шеврон + индекс активного.
/// Появляется, когда у сущности больше одного bbox. Клик раскрывает/сворачивает
/// список плашек (`BboxListView`) над тулбаром.
final class NavView: NSView {
    var onToggle: (() -> Void)?

    private let chevron = NSImageView()
    private let indexField = NSTextField(labelWithString: "1")
    private var isOpen = false

    override init(frame frameRect: NSRect) {
        super.init(frame: NSRect(x: 0, y: 0, width: 28, height: 64))
        wantsLayer = true

        chevron.image = NSImage(systemSymbolName: "chevron.up", accessibilityDescription: nil)
        chevron.contentTintColor = NSColor.white.withAlphaComponent(0.7)
        chevron.imageScaling = .scaleProportionallyDown
        chevron.translatesAutoresizingMaskIntoConstraints = false

        indexField.font = .monospacedSystemFont(ofSize: 12, weight: .semibold)
        indexField.textColor = NSColor.white.withAlphaComponent(0.85)
        indexField.alignment = .center
        indexField.isBezeled = false
        indexField.drawsBackground = false
        indexField.isEditable = false

        let stack = NSStackView(views: [chevron, indexField])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 2
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            chevron.widthAnchor.constraint(equalToConstant: 12),
            chevron.heightAnchor.constraint(equalToConstant: 10),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    func setIndex(_ index: Int) { indexField.stringValue = "\(index)" }

    func setOpen(_ open: Bool) {
        guard isOpen != open else { return }
        isOpen = open
        chevron.image = NSImage(systemSymbolName: open ? "chevron.down" : "chevron.up",
                                accessibilityDescription: nil)
    }

    override func resetCursorRects() {
        super.resetCursorRects()
        addCursorRect(bounds, cursor: .pointingHand)
    }

    override func mouseUp(with _: NSEvent) { onToggle?() }
}
