import AppKit

/// Тулбар режима разметки — морф из Default-виджета. Тот же визуальный язык
/// (outer/inner `WidgetPalette`, зелёный dot сверху-справа), набор контролов
/// строится из состояния `AnnotationModel` по матрице состояний макета:
///
/// `[Back] | [region segment] [tumor segment] | [Send]` — ровно два разделителя.
///
/// Сегмент сущности:
/// - empty            → `Add X` + `Mark Null`
/// - рисуется (tool)  → `Add X`(dim) + плашка-черновик(active) [+ навигация]
/// - есть bbox        → `Add X` + плашка активного bbox(×) [+ навигация при ≥2]
/// - null             → плашка `Null X`(×)
final class AnnotateToolbarView: NSView {
    var onBack: (() -> Void)?
    var onAddRegion: (() -> Void)?
    var onMarkNullRegion: (() -> Void)?
    var onClearRegion: (() -> Void)?       // × на Null Region → region=empty
    var onRemoveRegion: (() -> Void)?      // × на плашке активного region bbox
    var onAddTumor: (() -> Void)?
    var onMarkNullTumor: (() -> Void)?
    var onClearTumor: (() -> Void)?
    var onRemoveTumor: (() -> Void)?
    var onRegionPrev: (() -> Void)?
    var onRegionNext: (() -> Void)?
    var onTumorPrev: (() -> Void)?
    var onTumorNext: (() -> Void)?
    var onSend: (() -> Void)?

    private let outerLayer = CALayer()
    private let innerLayer = CALayer()
    private let statusDot = StatusDotView(frame: .zero)
    private let row = NSStackView()

    // Переиспользуемые контролы (без аллокаций при каждом rebuild → ресайз без мерцания).
    private let backButton = BackButtonView()
    private let sepAfterBack = AnnotateToolbarView.separator()
    private let sepBetween = AnnotateToolbarView.separator()   // Region | Tumor — разные секции
    private let sepBeforeSend = AnnotateToolbarView.separator()
    private let addRegionButton = ActionButtonView(icon: .add, label: "Add Region",
                                                   iconAlwaysOpaque: true)
    private let markNullRegionButton = ActionButtonView(icon: .markNull, label: "Mark Null",
                                                        iconAlwaysOpaque: true)
    private let regionPlate = CoordinatePlateView()
    private let regionNav = NavView()
    private let regionNullPill = NullPillView(title: "Null Region")
    private let addTumorButton = ActionButtonView(icon: .add, label: "Add Tumor",
                                                  iconAlwaysOpaque: true)
    private let markNullTumorButton = ActionButtonView(icon: .markNull, label: "Mark Null",
                                                       iconAlwaysOpaque: true)
    private let tumorPlate = CoordinatePlateView()
    private let tumorNav = NavView()
    private let tumorNullPill = NullPillView(title: "Null Tumor")
    private let sendButton = ActionButtonView(icon: .send, label: "Send", iconAlwaysOpaque: true)

    private let bodyHeight: CGFloat = 74
    private let dotOverflow: CGFloat = 8
    private let innerInset: CGFloat = 1
    private let rowInsetX: CGFloat = 8
    private let buttonHeight: CGFloat = 64
    private let buttonTopGap: CGFloat = 4   // как в Default-виджете

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

        wireControls()
        constrainFixedSizes()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    private func wireControls() {
        backButton.onClick = { [weak self] in self?.onBack?() }
        addRegionButton.onClick = { [weak self] in self?.onAddRegion?() }
        markNullRegionButton.onClick = { [weak self] in self?.onMarkNullRegion?() }
        regionNullPill.onClear = { [weak self] in self?.onClearRegion?() }
        regionPlate.onClear = { [weak self] in self?.onRemoveRegion?() }
        regionNav.onPrev = { [weak self] in self?.onRegionPrev?() }
        regionNav.onNext = { [weak self] in self?.onRegionNext?() }
        addTumorButton.onClick = { [weak self] in self?.onAddTumor?() }
        markNullTumorButton.onClick = { [weak self] in self?.onMarkNullTumor?() }
        tumorNullPill.onClear = { [weak self] in self?.onClearTumor?() }
        tumorPlate.onClear = { [weak self] in self?.onRemoveTumor?() }
        tumorNav.onPrev = { [weak self] in self?.onTumorPrev?() }
        tumorNav.onNext = { [weak self] in self?.onTumorNext?() }
        sendButton.onClick = { [weak self] in self?.onSend?() }
    }

    private func constrainFixedSizes() {
        heightOnly(backButton)   // Back — hug по содержимому (иконка + «Back»)
        for b in [addRegionButton, markNullRegionButton, addTumorButton, markNullTumorButton] {
            size(b, w: 82)
        }
        size(sendButton, w: 72)
        size(regionPlate, w: 132)
        size(tumorPlate, w: 132)
        size(regionNullPill, w: 116)
        size(tumorNullPill, w: 116)
        size(regionNav, w: 28)
        size(tumorNav, w: 28)
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

    // MARK: - Rebuild from model

    func apply(_ model: AnnotationModel, invalid: [UUID: ValidationError], draftRect: CGRect) {
        var views: [NSView] = [backButton, sepAfterBack]
        views += regionSegment(model, invalid: invalid, draftRect: draftRect)
        views.append(sepBetween)
        views += tumorSegment(model, invalid: invalid, draftRect: draftRect)
        views += [sepBeforeSend, sendButton]
        setArranged(views)

        sendButton.setEnabled(model.sendEnabled)
        needsLayout = true
    }

    /// Быстрое обновление координат черновика во время рисования (без перестройки стека).
    func updateDraft(rect: CGRect, tool: AnnotationTool) {
        let plate = tool == .addTumor ? tumorPlate : regionPlate
        plate.configure(rect: rect, isActive: true, isInvalid: false, showsClear: false)
    }

    private func regionSegment(_ model: AnnotationModel, invalid: [UUID: ValidationError],
                               draftRect: CGRect) -> [NSView] {
        if case .null = model.regionState {
            regionNullPill.setShowsClear(true)
            return [regionNullPill]
        }
        let toolActive = model.activeTool != .none
        addRegionButton.setEnabled(!toolActive)
        var seg: [NSView] = [addRegionButton]
        let committed = model.regionState.bboxes

        if model.activeTool == .addRegion {
            regionPlate.configure(rect: draftRect, isActive: true, isInvalid: false, showsClear: false)
            seg.append(regionPlate)
            if !committed.isEmpty { regionNav.setIndex(max(model.activeRegionIndex, 1)); seg.append(regionNav) }
        } else if let active = model.activeRegionBbox {
            regionPlate.configure(rect: active.rect, isActive: false,
                                  isInvalid: invalid[active.id] != nil, showsClear: true)
            seg.append(regionPlate)
            if committed.count >= 2 { regionNav.setIndex(model.activeRegionIndex); seg.append(regionNav) }
        } else {
            markNullRegionButton.setEnabled(!toolActive)
            seg.append(markNullRegionButton)
        }
        return seg
    }

    private func tumorSegment(_ model: AnnotationModel, invalid: [UUID: ValidationError],
                              draftRect: CGRect) -> [NSView] {
        if case .null = model.tumorState {
            tumorNullPill.setShowsClear(model.tumorControlsEnabled)   // × только при Region≠null
            return [tumorNullPill]
        }
        let toolActive = model.activeTool != .none
        addTumorButton.setEnabled(model.addTumorEnabled && !toolActive)
        var seg: [NSView] = [addTumorButton]
        let committed = model.tumorState.bboxes

        if model.activeTool == .addTumor {
            tumorPlate.configure(rect: draftRect, isActive: true, isInvalid: false, showsClear: false)
            seg.append(tumorPlate)
            if !committed.isEmpty { tumorNav.setIndex(max(model.activeTumorIndex, 1)); seg.append(tumorNav) }
        } else if let active = model.activeTumorBbox {
            tumorPlate.configure(rect: active.rect, isActive: false,
                                 isInvalid: invalid[active.id] != nil, showsClear: true)
            seg.append(tumorPlate)
            if committed.count >= 2 { tumorNav.setIndex(model.activeTumorIndex); seg.append(tumorNav) }
        } else {
            markNullTumorButton.setEnabled(!toolActive)
            seg.append(markNullTumorButton)
        }
        return seg
    }

    private func setArranged(_ views: [NSView]) {
        for v in row.arrangedSubviews {
            row.removeArrangedSubview(v)
            v.removeFromSuperview()
        }
        for v in views { row.addArrangedSubview(v) }
    }

    // MARK: - Sizing / layout

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
        // Кнопки на той же высоте, что и в Default-виджете: bottom-gap фикс, высота 64.
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
}
