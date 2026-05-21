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
    private var keyMonitor: Any?
    private var invalid: [UUID: ValidationError] = [:]
    private var draftRect: CGRect = .zero
    private let dotOverflow: CGFloat = 8   // == AnnotateToolbarView.dotOverflow (тело меньше панели)

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

        wireToolbar()
        wireOverlay()
        model.onChange = { [weak self] in self?.refresh() }
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
        installKeyMonitor()
    }

    private func finish() {
        let f = panel.frame
        let bodyCenter = NSPoint(x: f.minX + (f.width - dotOverflow) / 2,
                                 y: f.minY + (f.height - dotOverflow) / 2)
        removeKeyMonitor()
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
        toolbar.onRegionPrev = { [weak self] in self?.model.cycleRegion(-1) }
        toolbar.onRegionNext = { [weak self] in self?.model.cycleRegion(1) }
        toolbar.onTumorPrev = { [weak self] in self?.model.cycleTumor(-1) }
        toolbar.onTumorNext = { [weak self] in self?.model.cycleTumor(1) }
        toolbar.onSend = { [weak self] in self?.send() }
    }

    private func wireOverlay() {
        overlay.onDraw = { [weak self] rect, tool, monitor in
            guard let self else { return }
            let bbox = Bbox(rect: rect, monitorIndex: monitor)
            self.draftRect = .zero
            if tool == .addRegion { self.model.appendRegionBbox(bbox) }
            else { self.model.appendTumorBbox(bbox) }
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
        Task { @MainActor in
            await ensureOverlayPresented()
            guard overlay.isPresented else { return }
            draftRect = .zero
            if tool == .addRegion { model.activateAddRegion() }
            else { model.activateAddTumor() }
        }
    }

    @MainActor
    private func ensureOverlayPresented() async {
        guard !overlay.isPresented else { return }
        do {
            try await overlay.present()
            NSApp.activate(ignoringOtherApps: true)   // LSUIElement: нужно для приёма клавиш
            panel.orderFrontRegardless()
        } catch {
            presentPermissionAlert()
        }
    }

    private func presentPermissionAlert() {
        // Системный промпт уже показывает сам ScreenCaptureKit при «not determined»,
        // здесь — только подсказка про System Settings + обязательный перезапуск.
        let alert = NSAlert()
        alert.messageText = "Screen Recording permission required"
        alert.informativeText = "Enable BrainScan under System Settings → Privacy & Security → "
            + "Screen Recording, then quit and reopen BrainScan (macOS applies the grant only "
            + "after relaunch)."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn {
            let url = URL(string:
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!
            NSWorkspace.shared.open(url)
        }
    }

    // MARK: - Refresh

    private func refresh() {
        invalid = ValidationEngine.validate(region: model.regionState, tumor: model.tumorState)
        model.invalidBboxIds = Set(invalid.keys)
        toolbar.apply(model, invalid: invalid, draftRect: draftRect)
        resizePanelKeepingCenter()
        if overlay.isPresented { overlay.render(model: model, invalid: invalid) }
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
