import AppKit

/// Компактная навигация по нескольким bbox одной сущности: ▲ / индекс / ▼.
/// Появляется, когда у сущности больше одного bbox. Цифра — индекс активного.
final class NavView: NSView {
    var onPrev: (() -> Void)?   // ▲ — предыдущий
    var onNext: (() -> Void)?   // ▼ — следующий

    private let upButton = NavView.chevron("chevron.up")
    private let downButton = NavView.chevron("chevron.down")
    private let indexField = NSTextField(labelWithString: "1")

    override init(frame frameRect: NSRect) {
        super.init(frame: NSRect(x: 0, y: 0, width: 28, height: 64))
        wantsLayer = true

        indexField.font = .monospacedSystemFont(ofSize: 12, weight: .semibold)
        indexField.textColor = NSColor.white.withAlphaComponent(0.85)
        indexField.alignment = .center
        indexField.isBezeled = false
        indexField.drawsBackground = false
        indexField.isEditable = false

        let stack = NSStackView(views: [upButton, indexField, downButton])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 2
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])

        upButton.target = self
        upButton.action = #selector(prevTapped)
        downButton.target = self
        downButton.action = #selector(nextTapped)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    func setIndex(_ index: Int) { indexField.stringValue = "\(index)" }

    @objc private func prevTapped() { onPrev?() }
    @objc private func nextTapped() { onNext?() }

    private static func chevron(_ symbol: String) -> NSButton {
        let button = NSButton()
        button.isBordered = false
        button.bezelStyle = .regularSquare
        button.imageScaling = .scaleProportionallyDown
        button.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
        button.contentTintColor = NSColor.white.withAlphaComponent(0.7)
        button.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            button.widthAnchor.constraint(equalToConstant: 16),
            button.heightAnchor.constraint(equalToConstant: 12),
        ])
        return button
    }
}
