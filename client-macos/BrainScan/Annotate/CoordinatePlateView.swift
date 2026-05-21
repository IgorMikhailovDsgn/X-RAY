import AppKit

/// Плашка координат bbox (X/Y/W/H в logical-точках). Показывает координаты
/// активного/рисуемого bbox каждой сущности. Это индикатор, не кнопка:
/// fill `#FFFFFF 4%` по умолчанию → `10%` при hover/active. Невалидный bbox →
/// красный текст и обводка. В правом-верхнем углу — × для удаления bbox.
///
/// Стиль `.card` используется в выпадающем списке (`BboxListView`): непрозрачный
/// тёмный фон, т.к. плашка «плавает» над замороженным скриншотом без контейнера.
final class CoordinatePlateView: NSView {
    enum Style { case inline, card }

    /// Удалить связанный bbox (× в углу). Если nil — × скрыт (например, у черновика).
    var onClear: (() -> Void)?
    /// Клик по телу плашки (вне ×) — выбрать связанный bbox. Если nil — плашка не кликабельна.
    var onSelect: (() -> Void)?
    /// Курсор зашёл/вышел: enter → `bboxId`, exit → nil. Для двусторонней подсветки plate↔bbox.
    var onHover: ((UUID?) -> Void)?
    /// Связанный bbox (для подсветки).
    var bboxId: UUID?

    var style: Style = .inline { didSet { applyAppearance() } }

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
    /// Подсветка извне (курсор на самом bbox на оверлее) — освещает плашку.
    private var externallyLit = false

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
            col.alignment = .centerX
            col.spacing = 4
        }
        let row = NSStackView(views: [column1, column2])
        row.orientation = .horizontal
        row.distribution = .fillEqually
        row.spacing = 4
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
            row.centerYAnchor.constraint(equalTo: centerYAnchor),
            row.centerXAnchor.constraint(equalTo: centerXAnchor),
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

    /// Подсветить плашку, когда курсор на самом bbox (canvas → plate).
    func setExternallyLit(_ lit: Bool) {
        guard externallyLit != lit else { return }
        externallyLit = lit
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

    override func resetCursorRects() {
        super.resetCursorRects()
        if onSelect != nil { addCursorRect(bounds, cursor: .pointingHand) }
    }

    override func mouseEntered(with _: NSEvent) {
        hovered = true; applyAppearance(); onHover?(bboxId)
    }

    override func mouseExited(with _: NSEvent) {
        hovered = false; applyAppearance(); onHover?(nil)
    }

    override func mouseUp(with _: NSEvent) { onSelect?() }

    @objc private func clearTapped() { onClear?() }

    private func applyAppearance() {
        let lit = isActive || hovered || externallyLit
        switch style {
        case .inline:
            let base = lit ? NSColor.white.withAlphaComponent(0.10)
                           : NSColor.white.withAlphaComponent(0.04)
            backgroundLayer.backgroundColor = base.cgColor
        case .card:
            // Непрозрачная карточка поверх скриншота; hover чуть светлее.
            let base = lit ? NSColor.srgb(0x141B2E, alpha: 0.98)
                           : WidgetPalette.outerBackground
            backgroundLayer.backgroundColor = base.cgColor
        }
        backgroundLayer.borderColor = (isInvalid ? NSColor.systemRed : NSColor.clear).cgColor
        let textColor = isInvalid ? NSColor.systemRed : NSColor.white.withAlphaComponent(0.85)
        for f in [xField, yField, wField, hField] { f.textColor = textColor }
    }

    private static func makeField() -> NSTextField {
        let field = NSTextField(labelWithString: "")
        field.font = .monospacedSystemFont(ofSize: 12, weight: .medium)
        field.textColor = NSColor.white.withAlphaComponent(0.85)
        field.alignment = .center
        field.isBezeled = false
        field.drawsBackground = false
        field.isEditable = false
        field.translatesAutoresizingMaskIntoConstraints = false
        field.widthAnchor.constraint(equalToConstant: 50).isActive = true
        return field
    }
}

private extension NSColor {
    static func srgb(_ hex: UInt32, alpha: CGFloat) -> NSColor {
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255.0,
                green: CGFloat((hex >> 8) & 0xFF) / 255.0,
                blue: CGFloat(hex & 0xFF) / 255.0, alpha: alpha)
    }
}
