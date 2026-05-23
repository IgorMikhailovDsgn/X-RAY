import AppKit

/// Содержимое окна detect-оверлея на один монитор: затемнение живого экрана
/// (#02091A, 40% при детекции / 70% при результате или «не найдено») + HUD по
/// центру главного монитора (иконка + заголовок c pulse 100↔35% / Discard-текст
/// статичные 70%) + предсказанные region/tumor с прозрачными «дырками» внутри
/// и solid-обводкой (белый/оранжевый — тот же визуальный язык, что в разметке).
final class DetectOverlayView: NSView {
    private let isMain: Bool

    private var scrimAlpha: CGFloat = 0.40
    private var regionPredictions: [Bbox] = []
    private var tumorPredictions: [Bbox] = []

    // HUD = иконка + заголовок (pulse-анимация на всём контейнере).
    private let pulseGroup = NSStackView()
    private let iconView = NSImageView()
    private let titleLabel = NSTextField(labelWithString: "")

    init(isMain: Bool, frame: NSRect) {
        self.isMain = isMain
        super.init(frame: frame)
        wantsLayer = true

        guard isMain else { return }

        iconView.image = NSImage(named: "icon-search")
        iconView.image?.isTemplate = true
        iconView.contentTintColor = .white
        iconView.imageScaling = .scaleProportionallyUpOrDown
        iconView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            iconView.widthAnchor.constraint(equalToConstant: 48),
            iconView.heightAnchor.constraint(equalToConstant: 48),
        ])

        titleLabel.font = .systemFont(ofSize: 28, weight: .semibold)
        titleLabel.textColor = .white
        titleLabel.alignment = .center
        titleLabel.isBezeled = false
        titleLabel.drawsBackground = false
        titleLabel.isEditable = false

        pulseGroup.orientation = .vertical
        pulseGroup.alignment = .centerX
        pulseGroup.spacing = 16
        pulseGroup.wantsLayer = true
        pulseGroup.addArrangedSubview(iconView)
        pulseGroup.addArrangedSubview(titleLabel)
        pulseGroup.translatesAutoresizingMaskIntoConstraints = false
        addSubview(pulseGroup)
        NSLayoutConstraint.activate([
            pulseGroup.centerXAnchor.constraint(equalTo: centerXAnchor),
            pulseGroup.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])

        clearHUD()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override var isFlipped: Bool { true }

    // MARK: - Скрим и предсказания

    func setScrim(_ alpha: CGFloat) {
        scrimAlpha = alpha
        needsDisplay = true
    }

    func setPredictions(region: [Bbox], tumor: [Bbox]) {
        regionPredictions = region
        tumorPredictions = tumor
        needsDisplay = true
    }

    // MARK: - HUD

    func showDetecting(title: String) {
        guard isMain else { return }
        pulseGroup.isHidden = false
        iconView.isHidden = false
        titleLabel.stringValue = title
        startPulse()
    }

    func setDetectingTitle(_ title: String) {
        guard isMain else { return }
        titleLabel.stringValue = title
    }

    func showNotFound(title: String) {
        guard isMain else { return }
        pulseGroup.isHidden = false
        iconView.isHidden = true
        titleLabel.stringValue = title
        stopPulse()
    }

    func clearHUD() {
        guard isMain else { return }
        pulseGroup.isHidden = true
        stopPulse()
    }

    private func startPulse() {
        guard pulseGroup.layer?.animation(forKey: "pulse") == nil else { return }
        let anim = CABasicAnimation(keyPath: "opacity")
        anim.fromValue = 1.0
        anim.toValue = 0.35
        anim.duration = 0.75
        anim.autoreverses = true
        anim.repeatCount = .infinity
        anim.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        pulseGroup.layer?.add(anim, forKey: "pulse")
    }

    private func stopPulse() {
        pulseGroup.layer?.removeAnimation(forKey: "pulse")
        pulseGroup.layer?.opacity = 1.0
    }

    // MARK: - Drawing

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard let ctx = NSGraphicsContext.current else { return }

        Self.scrimColor.withAlphaComponent(scrimAlpha).setFill()
        NSBezierPath(rect: bounds).fill()

        // Дырки внутри предсказаний — видно живой экран, как в разметке.
        ctx.compositingOperation = .copy
        NSColor.clear.setFill()
        for box in regionPredictions { NSBezierPath(rect: box.rect).fill() }
        for box in tumorPredictions { NSBezierPath(rect: box.rect).fill() }
        ctx.compositingOperation = .sourceOver

        // Solid-обводки + подписи: region белый (тёмный текст), tumor оранжевый (белый текст).
        Self.regionColor.setStroke()
        for box in regionPredictions {
            let path = NSBezierPath(rect: box.rect)
            path.lineWidth = 2
            path.stroke()
        }
        Self.tumorColor.setStroke()
        for box in tumorPredictions {
            let path = NSBezierPath(rect: box.rect)
            path.lineWidth = 2
            path.stroke()
        }
        for (i, box) in regionPredictions.enumerated() {
            drawLabel("REGION \(i + 1)", at: box.rect,
                      background: Self.regionColor, text: Self.regionLabelText)
        }
        for (i, box) in tumorPredictions.enumerated() {
            drawLabel("TUMOR \(i + 1)", at: box.rect,
                      background: Self.tumorColor, text: .white)
        }
    }

    private func drawLabel(_ title: String, at rect: CGRect,
                           background: NSColor, text textColor: NSColor) {
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11, weight: .bold),
            .foregroundColor: textColor,
        ]
        let text = NSAttributedString(string: title, attributes: attrs)
        let textSize = text.size()
        let pad: CGFloat = 4
        let labelRect = CGRect(x: rect.minX, y: rect.minY - textSize.height - pad,
                               width: textSize.width + pad * 2, height: textSize.height + pad)
        background.setFill()
        NSBezierPath(roundedRect: labelRect, xRadius: 3, yRadius: 3).fill()
        text.draw(at: CGPoint(x: labelRect.minX + pad, y: labelRect.minY + pad / 2))
    }

    private static let scrimColor = NSColor(srgbRed: 0x02 / 255.0, green: 0x09 / 255.0,
                                            blue: 0x1A / 255.0, alpha: 1.0)
    private static let regionColor = NSColor.white
    private static let tumorColor = NSColor.systemOrange
    private static let regionLabelText = NSColor(srgbRed: 0x02 / 255.0, green: 0x09 / 255.0,
                                                 blue: 0x1A / 255.0, alpha: 1.0)
}
