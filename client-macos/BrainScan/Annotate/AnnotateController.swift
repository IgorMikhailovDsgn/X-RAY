import AppKit

/// Верхний оркестратор режима разметки: владеет `AnnotationModel`, плавающим
/// тулбаром и оверлеем. Связывает события тулбара/канваса с мутациями модели,
/// гоняет валидацию, обрабатывает hotkeys и Send. Оверлей открывается лениво —
/// при первом Add (скриншот замораживается в этот момент), Mark Null его не требует.
final class AnnotateController {
    /// Вызывается при завершении сессии (Back/Esc/Send). Передаёт центр тела
    /// тулбара — AppDelegate вернёт Default-виджет на то же место.
    var onFinished: ((NSPoint) -> Void)?

    private var model = AnnotationModel(entryMode: .annotate)
    private let toolbar = AnnotateToolbarView()
    private let overlay = OverlayController()
    private let panel: NSPanel
    private let dropdownPanel: NSPanel
    private let listView = BboxListView()
    /// Какой список открыт: nil — закрыт, true — tumor, false — region.
    private var openTumorList: Bool?
    private var keyMonitor: Any?
    private var invalid: [UUID: ValidationError] = [:]
    private var draftRect: CGRect = .zero
    private let dotOverflow: CGFloat = 8   // == AnnotateToolbarView.dotOverflow (тело меньше панели)
    private let dropdownGap: CGFloat = 8   // зазор между тулбаром и нижней плашкой списка

    init() {
        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 600, height: 82),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.isFloatingPanel = true
        // Над оверлеем (.screenSaver), чтобы тулбар оставался кликабельным.
        panel.level = NSWindow.Level(rawValue: NSWindow.Level.screenSaver.rawValue + 1)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.hasShadow = false
        panel.isMovableByWindowBackground = true   // перетаскивание как у Default-виджета
        panel.contentView = toolbar

        dropdownPanel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: BboxListView.plateWidth, height: 56),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        dropdownPanel.isFloatingPanel = true
        dropdownPanel.level = panel.level
        dropdownPanel.isOpaque = false
        dropdownPanel.backgroundColor = .clear
        dropdownPanel.hasShadow = false
        dropdownPanel.hidesOnDeactivate = false
        dropdownPanel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        dropdownPanel.contentView = listView

        wireToolbar()
        wireOverlay()
        wireDropdown()
        model.onChange = { [weak self] in self?.refresh() }
    }

    private func wireDropdown() {
        listView.onSelect = { [weak self] id in
            self?.model.select(id: id)
            self?.closeDropdown()
        }
        listView.onRemove = { [weak self] id in self?.model.removeBbox(id: id) }
        listView.onHover = { [weak self] id in self?.highlightBbox(id) }
    }

    // MARK: - Lifecycle

    /// `bodyCenter` — центр тела Default-виджета в экранных координатах: тулбар
    /// появляется на том же месте (морф «на месте»).
    func start(bodyCenter: NSPoint) {
        model = AnnotationModel(entryMode: .annotate)
        model.onChange = { [weak self] in self?.refresh() }
        invalid = [:]
        refresh()
        positionToolbar(bodyCenter: bodyCenter)
        panel.orderFrontRegardless()
        // Затемняющий overlay появляется сразу при входе в режим разметки.
        overlay.present()
        NSApp.activate(ignoringOtherApps: true)   // LSUIElement: нужно для приёма клавиш
        panel.orderFrontRegardless()              // тулбар над overlay
        refresh()
        installKeyMonitor()
    }

    private func finish() {
        let f = panel.frame
        let bodyCenter = NSPoint(x: f.minX + (f.width - dotOverflow) / 2,
                                 y: f.minY + (f.height - dotOverflow) / 2)
        removeKeyMonitor()
        closeDropdown()
        overlay.dismiss()
        panel.orderOut(nil)
        onFinished?(bodyCenter)
    }

    // MARK: - Wiring

    private func wireToolbar() {
        toolbar.onBack = { [weak self] in self?.finish() }
        toolbar.onAddRegion = { [weak self] in self?.beginTool(.addRegion) }
        toolbar.onAddTumor = { [weak self] in self?.beginTool(.addTumor) }
        toolbar.onMarkNullRegion = { [weak self] in self?.model.markNullRegion() }
        toolbar.onMarkNullTumor = { [weak self] in self?.model.markNullTumor() }
        toolbar.onClearRegion = { [weak self] in self?.model.clearRegion() }
        toolbar.onClearTumor = { [weak self] in self?.model.clearTumor() }
        toolbar.onRemoveRegion = { [weak self] in
            guard let id = self?.model.activeRegionId else { return }
            self?.model.removeBbox(id: id)
        }
        toolbar.onRemoveTumor = { [weak self] in
            guard let id = self?.model.activeTumorId else { return }
            self?.model.removeBbox(id: id)
        }
        toolbar.onRegionToggleList = { [weak self] in self?.toggleList(forTumor: false) }
        toolbar.onTumorToggleList = { [weak self] in self?.toggleList(forTumor: true) }
        toolbar.onHoverBbox = { [weak self] id in self?.highlightBbox(id) }
        toolbar.onSend = { [weak self] in self?.send() }
    }

    // MARK: - Подсветка и выпадающий список

    private func highlightBbox(_ id: UUID?) {
        overlay.highlight(id)
        refresh()
    }

    private func toggleList(forTumor: Bool) {
        if openTumorList == forTumor { closeDropdown() }
        else { openTumorList = forTumor; updateDropdown() }
    }

    private func updateDropdown() {
        guard let isTumor = openTumorList else { closeDropdown(); return }
        let boxes = isTumor ? model.tumorState.bboxes : model.regionState.bboxes
        let activeId = isTumor ? model.activeTumorId : model.activeRegionId
        guard boxes.count >= 2, let anchor = toolbar.navScreenFrame(forTumor: isTumor) else {
            closeDropdown(); return
        }
        listView.setItems(boxes, activeId: activeId,
                          hoveredId: overlay.currentHoveredId, invalid: invalid)
        let width = BboxListView.plateWidth
        let height = listView.fittingHeight(count: boxes.count)
        let origin = NSPoint(x: anchor.midX - width / 2, y: anchor.maxY + dropdownGap)
        dropdownPanel.setFrame(NSRect(origin: origin, size: CGSize(width: width, height: height)),
                               display: true)
        if dropdownPanel.parent == nil { panel.addChildWindow(dropdownPanel, ordered: .above) }
        dropdownPanel.orderFrontRegardless()
        toolbar.setListOpen(forTumor: isTumor, true)
        toolbar.setListOpen(forTumor: !isTumor, false)
    }

    private func closeDropdown() {
        if let isTumor = openTumorList { toolbar.setListOpen(forTumor: isTumor, false) }
        openTumorList = nil
        if dropdownPanel.parent != nil { panel.removeChildWindow(dropdownPanel) }
        dropdownPanel.orderOut(nil)
    }

    private func wireOverlay() {
        overlay.onDraw = { [weak self] rect, tool, monitor in
            guard let self else { return }
            let bbox = Bbox(rect: rect, monitorIndex: monitor)
            self.draftRect = .zero
            if tool == .addRegion { self.model.appendRegionBbox(bbox) }
            else { self.model.appendTumorBbox(bbox) }
            // Сразу выходим из инструмента → idle-режим, нарисованный bbox можно
            // двигать/растягивать. Новый рисуем повторным кликом Add.
            self.model.cancelTool()
        }
        overlay.onExitDrawMode = { [weak self] in self?.model.cancelTool() }
        overlay.onSelect = { [weak self] id in
            if let id { self?.model.select(id: id) } else { self?.refresh() }
        }
        overlay.onUpdate = { [weak self] id, rect in self?.model.updateBbox(id: id, rect: rect) }
        overlay.onHover = { [weak self] _ in self?.refresh() }
        overlay.onDraftLive = { [weak self] rect in
            guard let self else { return }
            self.draftRect = rect
            self.toolbar.updateDraft(rect: rect, tool: self.model.activeTool)
        }
    }

    private func beginTool(_ tool: AnnotationTool) {
        closeDropdown()
        guard overlay.isPresented else { return }
        draftRect = .zero
        if tool == .addRegion { model.activateAddRegion() }
        else { model.activateAddTumor() }
    }

    // MARK: - Refresh

    private func refresh() {
        invalid = ValidationEngine.validate(region: model.regionState, tumor: model.tumorState)
        model.invalidBboxIds = Set(invalid.keys)
        toolbar.apply(model, invalid: invalid, draftRect: draftRect,
                      hoveredId: overlay.currentHoveredId)
        resizePanelKeepingCenter()
        if overlay.isPresented { overlay.render(model: model, invalid: invalid) }
        if openTumorList != nil { updateDropdown() }
    }

    /// Ширина тулбара меняется при смене состава контролов — растём/сжимаемся
    /// симметрично от центра: центр тела (по X) остаётся на месте, низ — тоже.
    private func resizePanelKeepingCenter() {
        let newSize = toolbar.totalSize()
        let frame = panel.frame
        guard newSize != frame.size else { return }
        let bodyCenterX = frame.minX + (frame.width - dotOverflow) / 2
        let newX = bodyCenterX - (newSize.width - dotOverflow) / 2
        panel.setFrame(NSRect(x: newX, y: frame.minY,
                              width: newSize.width, height: newSize.height), display: true)
        toolbar.needsLayout = true
        toolbar.layoutSubtreeIfNeeded()
    }

    private func positionToolbar(bodyCenter: NSPoint) {
        let size = toolbar.totalSize()
        let bodyW = size.width - dotOverflow
        let bodyH = size.height - dotOverflow
        let origin = NSPoint(x: bodyCenter.x - bodyW / 2, y: bodyCenter.y - bodyH / 2)
        panel.setFrame(NSRect(origin: origin, size: size), display: true)
    }

    // MARK: - Send

    private func send() {
        guard model.sendEnabled else { return }
        let payload = AnnotationSubmitter.makePayload(model: model, snapshots: overlay.snapshots)
        AnnotationSubmitter.submit(payload)
        finish()
    }

    // MARK: - Hotkeys (R/T/N/Esc/⌘S), активны пока оверлей открыт

    private func installKeyMonitor() {
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            self?.handleKey(event) == true ? nil : event
        }
    }

    private func removeKeyMonitor() {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        keyMonitor = nil
    }

    /// Возвращает true, если событие поглощено.
    private func handleKey(_ event: NSEvent) -> Bool {
        if event.keyCode == 53 { finish(); return true }   // Esc
        let cmd = event.modifierFlags.contains(.command)
        switch event.charactersIgnoringModifiers?.lowercased() {
        case "s" where cmd: send(); return true
        case "r": beginTool(.addRegion); return true
        case "t": beginTool(.addTumor); return true
        case "n":
            if model.regionState == .empty { model.markNullRegion() }
            else if model.tumorControlsEnabled { model.markNullTumor() }
            return true
        default: return false
        }
    }
}
