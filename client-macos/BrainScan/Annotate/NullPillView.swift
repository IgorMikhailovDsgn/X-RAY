import AppKit

/// Плашка состояния `null` для сущности: «Null Region» / «Null Tumor» + кнопка ×
/// для сброса. Появляется в тулбаре, когда сущность помечена как отсутствующая.
final class NullPillView: NSView {
    var onClear: (() -> Void)?

    private let backgroundLayer = CALayer()
    private let labelView = NSTextField(labelWithString: "")
    private let clearButton = NSButton()
    private var clearWidth: NSLayoutConstraint!

    init(title: String) {
        super.init(frame: NSRect(x: 0, y: 0, width: 110, height: 64))
        wantsLayer = true
        backgroundLayer.backgroundColor = WidgetPalette.itemActiveBackground.cgColor
        backgroundLayer.cornerRadius = WidgetPalette.itemCornerRadius
        backgroundLayer.cornerCurve = .continuous
        layer?.addSublayer(backgroundLayer)

        labelView.stringValue = title
        labelView.font = .systemFont(ofSize: 12, weight: .medium)
        labelView.textColor = WidgetPalette.labelActive
        labelView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(labelView)

        clearButton.isBordered = false
        clearButton.bezelStyle = .regularSquare
        clearButton.imageScaling = .scaleProportionallyDown
        clearButton.image = NSImage(systemSymbolName: "xmark", accessibilityDescription: "Remove")
        clearButton.contentTintColor = NSColor.white.withAlphaComponent(0.6)
        clearButton.target = self
        clearButton.action = #selector(clearTapped)
        clearButton.translatesAutoresizingMaskIntoConstraints = false
        addSubview(clearButton)

        labelView.alignment = .center
        clearWidth = clearButton.widthAnchor.constraint(equalToConstant: 12)
        NSLayoutConstraint.activate([
            labelView.centerXAnchor.constraint(equalTo: centerXAnchor),
            labelView.centerYAnchor.constraint(equalTo: centerYAnchor),
            clearButton.topAnchor.constraint(equalTo: topAnchor, constant: 6),
            clearButton.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -8),
            clearButton.heightAnchor.constraint(equalToConstant: 12),
            clearWidth,
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    func setShowsClear(_ shows: Bool) {
        clearButton.isHidden = !shows
        clearWidth.constant = shows ? 12 : 0
    }

    override func layout() {
        super.layout()
        backgroundLayer.frame = bounds
    }

    @objc private func clearTapped() { onClear?() }
}
