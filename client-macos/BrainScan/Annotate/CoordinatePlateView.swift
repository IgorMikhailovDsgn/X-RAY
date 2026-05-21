import AppKit

/// Плашка координат bbox (X/Y/W/H в logical-точках). Показывает координаты
/// активного/рисуемого bbox каждой сущности. Это индикатор, не кнопка:
/// fill `#FFFFFF 4%` по умолчанию → `10%` при hover/active. Невалидный bbox →
/// красный текст и обводка. В правом-верхнем углу — × для удаления bbox.
final class CoordinatePlateView: NSView {
    /// Удалить связанный bbox (× в углу). Если nil — × скрыт (например, у черновика).
    var onClear: (() -> Void)?

    private let backgroundLayer = CALayer()
    private let xField = CoordinatePlateView.makeField()
    private let yField = CoordinatePlateView.makeField()
    private let wField = CoordinatePlateView.makeField()
    private let hField = CoordinatePlateView.makeField()
    private let clearButton = NSButton()
    private var trackingArea: NSTrackingArea?

    private var isActive = false
    private var isInvalid = false
    private var hovered = false

    private let defaultFill = NSColor.white.withAlphaComponent(0.04)
    private let activeFill = NSColor.white.withAlphaComponent(0.10)

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        backgroundLayer.cornerRadius = WidgetPalette.itemCornerRadius
        backgroundLayer.cornerCurve = .continuous
        backgroundLayer.borderWidth = 1
        backgroundLayer.borderColor = NSColor.clear.cgColor
        layer?.addSublayer(backgroundLayer)

        let column1 = NSStackView(views: [xField, wField])
        let column2 = NSStackView(views: [yField, hField])
        for col in [column1, column2] {
            col.orientation = .vertical
            col.alignment = .leading
            col.spacing = 4
        }
        let row = NSStackView(views: [column1, column2])
        row.orientation = .horizontal
        row.distribution = .fillEqually
        row.spacing = 14
        row.translatesAutoresizingMaskIntoConstraints = false
        addSubview(row)

        clearButton.isBordered = false
        clearButton.bezelStyle = .regularSquare
        clearButton.imageScaling = .scaleProportionallyDown
        clearButton.image = NSImage(systemSymbolName: "xmark", accessibilityDescription: "Remove")
        clearButton.contentTintColor = NSColor.white.withAlphaComponent(0.6)
        clearButton.target = self
        clearButton.action = #selector(clearTapped)
        clearButton.translatesAutoresizingMaskIntoConstraints = false
        addSubview(clearButton)

        NSLayoutConstraint.activate([
            row.centerYAnchor.constraint(equalTo: centerYAnchor, constant: 4),
            row.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            row.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -10),
            clearButton.topAnchor.constraint(equalTo: topAnchor, constant: 6),
            clearButton.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -6),
            clearButton.widthAnchor.constraint(equalToConstant: 12),
            clearButton.heightAnchor.constraint(equalToConstant: 12),
        ])
        applyAppearance()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func layout() {
        super.layout()
        backgroundLayer.frame = bounds
    }

    func configure(rect: CGRect?, isActive: Bool, isInvalid: Bool, showsClear: Bool) {
        let r = rect ?? .zero
        xField.stringValue = "X: \(Int(r.origin.x.rounded()))"
        yField.stringValue = "Y: \(Int(r.origin.y.rounded()))"
        wField.stringValue = "W: \(Int(r.width.rounded()))"
        hField.stringValue = "H: \(Int(r.height.rounded()))"
        self.isActive = isActive
        self.isInvalid = isInvalid
        clearButton.isHidden = !showsClear
        applyAppearance()
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea { removeTrackingArea(trackingArea) }
        let area = NSTrackingArea(rect: bounds,
                                  options: [.mouseEnteredAndExited, .activeAlways],
                                  owner: self, userInfo: nil)
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseEntered(with _: NSEvent) { hovered = true; applyAppearance() }
    override func mouseExited(with _: NSEvent) { hovered = false; applyAppearance() }

    @objc private func clearTapped() { onClear?() }

    private func applyAppearance() {
        let lit = isActive || hovered
        backgroundLayer.backgroundColor = (lit ? activeFill : defaultFill).cgColor
        backgroundLayer.borderColor = (isInvalid ? NSColor.systemRed : NSColor.clear).cgColor
        let textColor = isInvalid ? NSColor.systemRed : NSColor.white.withAlphaComponent(0.85)
        for f in [xField, yField, wField, hField] { f.textColor = textColor }
    }

    private static func makeField() -> NSTextField {
        let field = NSTextField(labelWithString: "")
        field.font = .monospacedSystemFont(ofSize: 12, weight: .medium)
        field.textColor = NSColor.white.withAlphaComponent(0.85)
        field.isBezeled = false
        field.drawsBackground = false
        field.isEditable = false
        return field
    }
}
