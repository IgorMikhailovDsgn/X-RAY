import AppKit

/// Нижний тулбар Detect-режима в визуальном языке виджета (outer/inner контейнер,
/// зелёный dot, те же `BackButtonView`/`CoordinatePlateView`/`NullPillView`/`ActionButtonView`).
/// Структура — как у `AnnotateToolbarView`:
/// `[Back | Region(plate/Empty) | sep | Tumor(plate/Empty) | sep | (Approve|Confirm) | Edit]`.
/// Если bbox не найдены — middle-кнопка «Confirm», в сегментах плашки «Empty Region/Tumor».
/// При Edit-транзишене модель аннотации получает предзаполнение из этих же предсказаний.
final class DetectActionsToolbarView: NSView {
    var onBack: (() -> Void)?
    var onApprove: (() -> Void)?
    var onEdit: (() -> Void)?
    var onDiscard: (() -> Void)?

    private let outerLayer = CALayer()
    private let innerLayer = CALayer()
    private let statusDot = StatusDotView(frame: .zero)
    private let row = NSStackView()

    private let backButton = BackButtonView()
    private let sepAfterBack = DetectActionsToolbarView.separator()
    private let sepBetween = DetectActionsToolbarView.separator()
    private let sepBeforeActions = DetectActionsToolbarView.separator()

    private let regionPlate = CoordinatePlateView()
    private let regionNullPill = NullPillView(title: "Null Region")
    private let tumorPlate = CoordinatePlateView()
    private let tumorNullPill = NullPillView(title: "Null Tumor")

    private let approveButton = ActionButtonView(icon: .check, label: "Approve", iconAlwaysOpaque: true)
    private let confirmButton = ActionButtonView(icon: .check, label: "Confirm", iconAlwaysOpaque: true)
    private let editButton = ActionButtonView(icon: .annotate, label: "Edit", iconAlwaysOpaque: true)
    private let discardButton = ActionButtonView(icon: .discard, label: "Discard", iconAlwaysOpaque: true)

    private let bodyHeight: CGFloat = 74
    private let dotOverflow: CGFloat = 8
    private let innerInset: CGFloat = 1
    private let rowInsetX: CGFloat = 8
    private let buttonHeight: CGFloat = 64
    private let buttonTopGap: CGFloat = 4

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.masksToBounds = false

        outerLayer.backgroundColor = WidgetPalette.outerBackground.cgColor
        outerLayer.cornerRadius = WidgetPalette.outerCornerRadius
        outerLayer.cornerCurve = .continuous
        layer?.addSublayer(outerLayer)

        innerLayer.backgroundColor = WidgetPalette.innerFill.cgColor
        innerLayer.cornerRadius = WidgetPalette.innerCornerRadius
        innerLayer.cornerCurve = .continuous
        innerLayer.borderWidth = 1
        innerLayer.borderColor = WidgetPalette.innerStroke.cgColor
        innerLayer.masksToBounds = true
        layer?.addSublayer(innerLayer)

        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 6
        row.translatesAutoresizingMaskIntoConstraints = false
        addSubview(row)

        statusDot.fillColor = .systemGreen
        addSubview(statusDot)

        backButton.onClick = { [weak self] in self?.onBack?() }
        approveButton.onClick = { [weak self] in self?.onApprove?() }
        confirmButton.onClick = { [weak self] in self?.onApprove?() }
        editButton.onClick = { [weak self] in self?.onEdit?() }
        discardButton.onClick = { [weak self] in self?.onDiscard?() }

        regionNullPill.setShowsClear(false)
        tumorNullPill.setShowsClear(false)

        heightOnly(backButton)
        for b in [approveButton, confirmButton, editButton, discardButton] { size(b, w: 82) }
        size(regionPlate, w: 126)
        size(tumorPlate, w: 126)
        size(regionNullPill, w: 116)
        size(tumorNullPill, w: 116)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    /// Конфигурация во время Detecting — только Discard.
    func configureDetecting() {
        setArranged([discardButton])
        needsLayout = true
    }

    /// Сборка тулбара под результат детекции. Plate'ы показывают первую
    /// найденную сущность каждого типа (overlay рисует все); полное
    /// редактирование списка — в Edit → Annotate.
    func configure(result: DetectResult) {
        let prediction = result.predictions.first
        let regionBox = prediction?.regions.first
        let tumorBox = prediction?.tumors.first

        var views: [NSView] = [backButton, sepAfterBack]
        if let regionBox {
            regionPlate.bboxId = regionBox.id
            regionPlate.configure(rect: regionBox.rect, isActive: false,
                                  isInvalid: false, showsClear: false)
            views.append(regionPlate)
        } else {
            views.append(regionNullPill)
        }
        views.append(sepBetween)
        if let tumorBox {
            tumorPlate.bboxId = tumorBox.id
            tumorPlate.configure(rect: tumorBox.rect, isActive: false,
                                 isInvalid: false, showsClear: false)
            views.append(tumorPlate)
        } else {
            views.append(tumorNullPill)
        }
        views.append(sepBeforeActions)
        views.append(result.hasAnyRegion ? approveButton : confirmButton)
        views.append(editButton)

        setArranged(views)
        needsLayout = true
    }

    /// Цвет status-точки — отражает реальный статус сервера/очереди (см. AppDelegate).
    func setDotColor(_ color: NSColor) {
        statusDot.fillColor = color
    }

    func totalSize() -> CGSize {
        row.layoutSubtreeIfNeeded()
        let bodyWidth = row.fittingSize.width + 2 * (innerInset + rowInsetX)
        return CGSize(width: bodyWidth + dotOverflow, height: bodyHeight + dotOverflow)
    }

    override func layout() {
        super.layout()
        let bodyWidth = bounds.width - dotOverflow
        let bodyRect = CGRect(x: 0, y: 0, width: bodyWidth, height: bodyHeight)
        outerLayer.frame = bodyRect
        let innerRect = bodyRect.insetBy(dx: innerInset, dy: innerInset)
        innerLayer.frame = innerRect
        row.frame = CGRect(
            x: innerRect.minX + rowInsetX,
            y: bodyRect.maxY - buttonTopGap - buttonHeight,
            width: innerRect.width - 2 * rowInsetX,
            height: buttonHeight
        )
        let dotDiameter: CGFloat = 16
        statusDot.frame = NSRect(
            x: bodyRect.maxX - 2 - dotDiameter / 2,
            y: bodyRect.maxY - 2 - dotDiameter / 2,
            width: dotDiameter, height: dotDiameter
        )
    }

    private func setArranged(_ views: [NSView]) {
        for v in row.arrangedSubviews {
            row.removeArrangedSubview(v)
            v.removeFromSuperview()
        }
        for v in views { row.addArrangedSubview(v) }
    }

    private func size(_ view: NSView, w: CGFloat) {
        view.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            view.widthAnchor.constraint(equalToConstant: w),
            view.heightAnchor.constraint(equalToConstant: buttonHeight),
        ])
    }

    private func heightOnly(_ view: NSView) {
        view.translatesAutoresizingMaskIntoConstraints = false
        view.heightAnchor.constraint(equalToConstant: buttonHeight).isActive = true
    }

    private static func separator() -> NSView {
        let v = NSView()
        v.wantsLayer = true
        v.layer?.backgroundColor = WidgetPalette.separator.cgColor
        v.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            v.widthAnchor.constraint(equalToConstant: 1),
            v.heightAnchor.constraint(equalToConstant: 38),
        ])
        return v
    }
}
