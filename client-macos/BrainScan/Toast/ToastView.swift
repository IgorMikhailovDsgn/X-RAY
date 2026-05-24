import AppKit

/// Плашка-уведомление: иконка + текст в стиле виджет-индикатора
/// (`outerBackground` + `outerCornerRadius`, белый текст). Используется как
/// тост над виджетом — управляет показом `ToastController`.
final class ToastView: NSView {
    private let bg = CALayer()
    private let iconView = NSImageView()
    private let labelView = NSTextField(labelWithString: "")

    init(icon: NSImage?, iconTint: NSColor, text: String) {
        super.init(frame: .zero)
        wantsLayer = true
        bg.backgroundColor = WidgetPalette.outerBackground.cgColor
        bg.cornerRadius = WidgetPalette.outerCornerRadius
        bg.cornerCurve = .continuous
        layer?.addSublayer(bg)

        if let icon { icon.isTemplate = true }
        iconView.image = icon
        iconView.contentTintColor = iconTint
        iconView.imageScaling = .scaleProportionallyUpOrDown
        iconView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(iconView)

        labelView.stringValue = text
        labelView.font = .systemFont(ofSize: 13, weight: .medium)
        labelView.textColor = .white
        labelView.isBezeled = false
        labelView.drawsBackground = false
        labelView.isEditable = false
        labelView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(labelView)

        NSLayoutConstraint.activate([
            iconView.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 14),
            iconView.centerYAnchor.constraint(equalTo: centerYAnchor),
            iconView.widthAnchor.constraint(equalToConstant: 18),
            iconView.heightAnchor.constraint(equalToConstant: 18),
            labelView.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 10),
            labelView.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -16),
            labelView.topAnchor.constraint(equalTo: topAnchor, constant: 10),
            labelView.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -10),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func layout() {
        super.layout()
        bg.frame = bounds
    }
}
