import AppKit

/// Тип сущности bbox — задаёт цвет и подпись на оверлее.
enum BboxKind { case region, tumor }

/// Готовый к отрисовке bbox (контроллер пушит снапшот после каждой мутации модели).
struct RenderBox {
    let id: UUID
    let rect: CGRect      // logical-точки, top-left origin (как isFlipped-канвас)
    let kind: BboxKind
    let index: Int        // 1-based индекс для маркера
    let isInvalid: Bool
    let isActive: Bool
}

/// Канвас разметки поверх замороженного скриншота одного монитора.
/// Координаты — flipped (y растёт вниз), совпадают с logical-семантикой модели.
///
/// Режимы:
/// - активный инструмент (Add Region/Tumor) → crosshair, рисование нового bbox;
///   bbox < 10px трактуется как «клик без рисования» → выход из режима;
/// - idle → выбор/перемещение/resize существующих bbox по ручкам.
final class BboxCanvasView: NSView {
    let monitorIndex: Int

    var activeTool: AnnotationTool = .none {
        didSet { if oldValue != activeTool { resetCursorAndState() } }   // иначе render обрывает drag
    }

    // Колбэки в контроллер.
    var onDrawCommitted: ((_ rect: CGRect, _ tool: AnnotationTool) -> Void)?
    var onExitDrawMode: (() -> Void)?
    var onBboxSelected: ((UUID?) -> Void)?
    var onBboxUpdated: ((_ id: UUID, _ rect: CGRect) -> Void)?
    var onHoverBbox: ((UUID?) -> Void)?
    var onDraftChanged: ((CGRect) -> Void)?   // живые координаты во время рисования

    private var boxes: [RenderBox] = []
    private var trackingArea: NSTrackingArea?

    // Состояние взаимодействия.
    private var drawOrigin: CGPoint?
    private var draftRect: CGRect?
    private var dragContext: DragContext?

    private let minSide: CGFloat = 10
    private let handleSize: CGFloat = 8        // визуальный размер ручки
    private let handleHitSize: CGFloat = 18    // зона захвата ручки (больше визуальной)
    private let hitSlop: CGFloat = 6

    init(monitorIndex: Int) {
        self.monitorIndex = monitorIndex
        super.init(frame: .zero)
        wantsLayer = true
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }

    /// Доставлять клик во вьюху, даже если оверлей-окно не key (key — панель тулбара).
    /// Иначе первый mouseDown «съедается» на активацию окна и drag (move/resize) не стартует.
    override func acceptsFirstMouse(for _: NSEvent?) -> Bool { true }

    func setBoxes(_ boxes: [RenderBox]) {
        self.boxes = boxes
        needsDisplay = true
        window?.invalidateCursorRects(for: self)   // геометрия изменилась → пересобрать курсор-rect'ы
    }

    // MARK: - Cursor / tracking

    private func resetCursorAndState() {
        drawOrigin = nil
        draftRect = nil
        dragContext = nil
        window?.invalidateCursorRects(for: self)
        needsDisplay = true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea { removeTrackingArea(trackingArea) }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways],
            owner: self, userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    /// Курсоры через канонические курсор-rect'ы (надёжнее cursorUpdate): crosshair
    /// при активном инструменте, resize на ручках активного bbox, «рука» на телах.
    override func resetCursorRects() {
        super.resetCursorRects()
        if activeTool != .none {
            addCursorRect(bounds, cursor: .crosshair)
            return
        }
        for box in boxes { addCursorRect(box.rect, cursor: .openHand) }
        // Ручки всех активных боксов; tumor добавляем последним → его ручки выигрывают
        // при перекрытии (последний addCursorRect имеет приоритет).
        for active in boxes.filter({ $0.isActive }) {
            for mode in ResizeMode.allCases {
                addCursorRect(mode.handleRect(for: active.rect, size: handleHitSize),
                              cursor: mode.cursor)
            }
        }
    }

    // MARK: - Mouse

    override func mouseMoved(with event: NSEvent) {
        guard activeTool == .none else { return }
        let p = convert(event.locationInWindow, from: nil)
        onHoverBbox?(hitTestBox(at: p)?.id)
    }

    override func mouseExited(with _: NSEvent) {
        onHoverBbox?(nil)
    }

    override func mouseDown(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        // Ручки активного bbox можно тянуть в любом режиме — в т.ч. во время рисования,
        // чтобы подправить только что нарисованный прямоугольник.
        if let ctx = resizeContext(at: p) { dragContext = ctx; return }

        if activeTool != .none {
            // По пустому месту/внутри — рисуем новый bbox (tumor рисуется внутри region).
            drawOrigin = p
            draftRect = CGRect(origin: p, size: .zero)
            onDraftChanged?(.zero)
            return
        }
        // idle: тело bbox → выбрать + move; пусто → снять выбор.
        if let box = hitTestBox(at: p) {
            onBboxSelected?(box.id)
            dragContext = DragContext(id: box.id, mode: .move,
                                      startMouse: p, startRect: box.rect)
        } else {
            onBboxSelected?(nil)
        }
    }

    override func mouseDragged(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        // Редактирование (resize/move) активного bbox имеет приоритет над рисованием.
        if let ctx = dragContext {
            let dx = p.x - ctx.startMouse.x
            let dy = p.y - ctx.startMouse.y
            let newRect = ctx.mode == .move
                ? ctx.startRect.offsetBy(dx: dx, dy: dy)
                : ctx.mode.resized(ctx.startRect, dx: dx, dy: dy)
            onBboxUpdated?(ctx.id, newRect)
            return
        }
        if activeTool != .none, let origin = drawOrigin {
            let rect = rectBetween(origin, p)
            draftRect = rect
            onDraftChanged?(rect)
            needsDisplay = true
        }
    }

    override func mouseUp(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        defer { drawOrigin = nil; draftRect = nil; dragContext = nil; needsDisplay = true }

        guard activeTool != .none, let origin = drawOrigin else { return }
        let rect = rectBetween(origin, p)
        // Клик без рисования / слишком маленький bbox → выходим из режима.
        if rect.width < minSide || rect.height < minSide {
            onExitDrawMode?()
        } else {
            onDrawCommitted?(rect, activeTool)
        }
    }

    override func keyDown(with event: NSEvent) {
        // Esc обрабатывает OverlayController через монитор; здесь — заглушаем beep.
        if event.keyCode == 53 { return }
        super.keyDown(with: event)
    }

    // MARK: - Hit-testing

    private func hitTestBox(at p: CGPoint) -> RenderBox? {
        boxes.last { $0.rect.insetBy(dx: -hitSlop, dy: -hitSlop).contains(p) }
    }

    private func resizeContext(at p: CGPoint) -> DragContext? {
        // Активными могут быть оба бокса (region+tumor) одновременно. Проверяем ручки
        // всех активных, начиная с верхнего (tumor поверх region при перекрытии ручек).
        for active in boxes.filter({ $0.isActive }).reversed() {
            for mode in ResizeMode.allCases {
                let handle = mode.handleRect(for: active.rect, size: handleHitSize)
                if handle.contains(p) {
                    return DragContext(id: active.id, mode: mode,
                                       startMouse: p, startRect: active.rect)
                }
            }
        }
        return nil
    }

    private func rectBetween(_ a: CGPoint, _ b: CGPoint) -> CGRect {
        CGRect(x: min(a.x, b.x), y: min(a.y, b.y),
               width: abs(a.x - b.x), height: abs(a.y - b.y))
    }

    // MARK: - Drawing

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard let ctx = NSGraphicsContext.current else { return }

        // 1. Затемняющий скрим (#02091A 50%) поверх всего живого экрана.
        Self.scrimColor.setFill()
        NSBezierPath(rect: bounds).fill()

        // 2. «Дырки» 0% opacity внутри каждого bbox и текущего черновика —
        //    .copy с прозрачным цветом вырезает скрим, открывая живой экран.
        ctx.compositingOperation = .copy
        NSColor.clear.setFill()
        for box in boxes { NSBezierPath(rect: box.rect).fill() }
        if let draft = draftRect { NSBezierPath(rect: draft).fill() }
        ctx.compositingOperation = .sourceOver

        // 3. Обводки/подписи/ручки поверх.
        for box in boxes { drawBox(box) }
        if let draft = draftRect {
            let color = activeTool == .addTumor ? Self.tumorColor : Self.regionColor
            color.withAlphaComponent(0.9).setStroke()
            let path = NSBezierPath(rect: draft)
            path.lineWidth = 2
            path.stroke()
        }
    }

    private func drawBox(_ box: RenderBox) {
        let baseColor: NSColor = box.isInvalid
            ? Self.invalidColor
            : (box.kind == .region ? Self.regionColor : Self.tumorColor)

        // Внутренность — прозрачная «дырка» (вырезана в скриме), заливки нет.
        baseColor.setStroke()
        let path = NSBezierPath(rect: box.rect)
        path.lineWidth = box.isActive ? 3 : 2
        path.stroke()

        drawLabel(for: box, color: baseColor)
        if box.isActive { drawHandles(for: box.rect, color: baseColor) }
    }

    private func drawLabel(for box: RenderBox, color: NSColor) {
        let title = "\(box.kind == .region ? "REGION" : "TUMOR") \(box.index)"
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11, weight: .bold),
            .foregroundColor: NSColor.white,
        ]
        let text = NSAttributedString(string: title, attributes: attrs)
        let textSize = text.size()
        let pad: CGFloat = 4
        let labelRect = CGRect(x: box.rect.minX, y: box.rect.minY - textSize.height - pad,
                               width: textSize.width + pad * 2, height: textSize.height + pad)
        color.setFill()
        NSBezierPath(roundedRect: labelRect, xRadius: 3, yRadius: 3).fill()
        text.draw(at: CGPoint(x: labelRect.minX + pad, y: labelRect.minY + pad / 2))
    }

    private func drawHandles(for rect: CGRect, color: NSColor) {
        for mode in ResizeMode.allCases {
            let h = mode.handleRect(for: rect, size: handleSize)
            NSColor.white.setFill()
            color.setStroke()
            let path = NSBezierPath(ovalIn: h)
            path.lineWidth = 1.5
            path.fill()
            path.stroke()
        }
    }

    // Цвета.
    private static let regionColor = NSColor.systemTeal
    private static let tumorColor = NSColor.systemOrange
    private static let invalidColor = NSColor.systemRed
    /// Затемнение живого экрана вне bbox: #02091A 50%.
    private static let scrimColor = NSColor(srgbRed: 0x02 / 255.0, green: 0x09 / 255.0,
                                            blue: 0x1A / 255.0, alpha: 0.5)
}

// MARK: - Drag/resize support

private struct DragContext {
    let id: UUID
    let mode: ResizeMode
    let startMouse: CGPoint
    let startRect: CGRect
}

/// Режимы перетаскивания: move (всё тело) + 8 ручек resize.
private enum ResizeMode: CaseIterable {
    case move
    case topLeft, top, topRight, right, bottomRight, bottom, bottomLeft, left

    static var allCases: [ResizeMode] {
        [.topLeft, .top, .topRight, .right, .bottomRight, .bottom, .bottomLeft, .left]
    }

    func handleRect(for r: CGRect, size: CGFloat) -> CGRect {
        let point: CGPoint
        switch self {
        case .topLeft:     point = CGPoint(x: r.minX, y: r.minY)
        case .top:         point = CGPoint(x: r.midX, y: r.minY)
        case .topRight:    point = CGPoint(x: r.maxX, y: r.minY)
        case .right:       point = CGPoint(x: r.maxX, y: r.midY)
        case .bottomRight: point = CGPoint(x: r.maxX, y: r.maxY)
        case .bottom:      point = CGPoint(x: r.midX, y: r.maxY)
        case .bottomLeft:  point = CGPoint(x: r.minX, y: r.maxY)
        case .left:        point = CGPoint(x: r.minX, y: r.midY)
        case .move:        point = CGPoint(x: r.midX, y: r.midY)
        }
        return CGRect(x: point.x - size / 2, y: point.y - size / 2, width: size, height: size)
    }

    /// Курсор для idle-наведения на ручку. Диагональных resize-курсоров в публичном
    /// AppKit нет → углам даём crosshair, сторонам — горизонтальный/вертикальный.
    var cursor: NSCursor {
        switch self {
        case .left, .right:        return .resizeLeftRight
        case .top, .bottom:        return .resizeUpDown
        case .topLeft, .topRight, .bottomLeft, .bottomRight: return .crosshair
        case .move:                return .openHand
        }
    }

    func resized(_ r: CGRect, dx: CGFloat, dy: CGFloat) -> CGRect {
        var minX = r.minX, minY = r.minY, maxX = r.maxX, maxY = r.maxY
        switch self {
        case .topLeft:     minX += dx; minY += dy
        case .top:         minY += dy
        case .topRight:    maxX += dx; minY += dy
        case .right:       maxX += dx
        case .bottomRight: maxX += dx; maxY += dy
        case .bottom:      maxY += dy
        case .bottomLeft:  minX += dx; maxY += dy
        case .left:        minX += dx
        case .move:        break
        }
        return CGRect(x: min(minX, maxX), y: min(minY, maxY),
                      width: abs(maxX - minX), height: abs(maxY - minY))
    }
}
