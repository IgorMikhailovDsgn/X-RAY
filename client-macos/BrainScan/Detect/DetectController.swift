import AppKit

/// Оркестратор Detect-режима (Phase 9: реальный inference через POST /detect).
/// Поток: Detecting (HUD по центру экрана с pulse + Discard-текст) → захват
/// primary-монитора → uploadScreenshot → /detect → конвертация bbox (physical
/// → logical с Y-flip) → Detect Actions тулбар в позиции виджета:
/// `[Back | Region | Tumor | Approve/Confirm | Edit]`.
final class DetectController {
    /// Завершение режима (Back/Discard/Approve) — AppDelegate показывает виджет
    /// обратно в его исходной позиции.
    var onFinished: (() -> Void)?
    /// Переход в коррекцию: отдаём предзаполнение Region/Tumor для Edit-оверлея.
    var onEdit: (((region: EntityState, tumor: EntityState)) -> Void)?

    private let overlay = DetectOverlayController()
    private let toolbar = DetectActionsToolbarView()
    private let panel: NSPanel
    private var keyMonitor: Any?
    private var result: DetectResult?
    private var longerWork: DispatchWorkItem?
    /// Центр тела виджета на момент входа в режим — тулбар появляется здесь же
    /// и сюда же возвращается виджет.
    private var bodyCenter: NSPoint = .zero

    private let dotOverflow: CGFloat = 8

    init() {
        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 82),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.isFloatingPanel = true
        panel.level = NSWindow.Level(rawValue: NSWindow.Level.screenSaver.rawValue + 1)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.hasShadow = false
        panel.isMovableByWindowBackground = true   // тулбар можно перетаскивать
        panel.contentView = toolbar

        toolbar.onBack = { [weak self] in self?.finish() }
        toolbar.onApprove = { [weak self] in self?.approve() }
        toolbar.onEdit = { [weak self] in self?.edit() }
        toolbar.onDiscard = { [weak self] in self?.finish() }
    }

    // MARK: - Lifecycle

    /// Цвет status-точки тулбара — синхронизирован с виджетом (см. AppDelegate).
    func setStatusDotColor(_ color: NSColor) { toolbar.setDotColor(color) }

    /// `bodyCenter` — центр тела Default-виджета в экранных координатах. Тулбар
    /// Detect Actions появляется в этой же позиции (правило «куда поставил —
    /// там и остаётся»).
    func start(bodyCenter: NSPoint) {
        self.bodyCenter = bodyCenter
        // Gate: Screen Recording обязателен — без него ни захватить, ни
        // отрисовать оверлей нет смысла. Если юзер откажет, повторный клик
        // снова поднимет системный промпт (см. PermissionGate).
        PermissionGate.ensureScreenRecording { [weak self] granted in
            guard let self else { return }
            guard granted else {
                ToastController.shared.show(
                    text: "Enable Screen Recording in System Settings",
                    icon: Icon24.discard.makeImage(pointSize: 16),
                    iconTint: .systemOrange,
                    near: bodyCenter
                )
                self.onFinished?()
                return
            }
            self.beginDetectSession()
        }
    }

    private func beginDetectSession() {
        result = nil
        overlay.present()
        overlay.showDetecting()
        // Тулбар на месте виджета: во время Detecting — только Discard, после результата
        // — Back/Region/Tumor/Approve|Confirm/Edit.
        toolbar.configureDetecting()
        positionToolbar()
        panel.orderFrontRegardless()
        NSApp.activate(ignoringOtherApps: true)
        installKeyMonitor()
        Task { await runRealDetect() }
    }

    private func finish() {
        cancelWork()
        removeKeyMonitor()
        overlay.dismiss()
        panel.orderOut(nil)
        onFinished?()
    }

    // MARK: - Real detect

    /// Покажет «It takes longer…» если до результата не дошло за 5 c (cold-start
    /// inference на CPU server'е: lazy torch import + 2 weight download).
    private func scheduleLongerHint() {
        let longer = DispatchWorkItem { [weak self] in self?.overlay.showLongerMessage() }
        longerWork = longer
        DispatchQueue.main.asyncAfter(deadline: .now() + 5.0, execute: longer)
    }

    private func runRealDetect() async {
        await MainActor.run { self.scheduleLongerHint() }
        do {
            guard let primary = DisplaySnapshot.forPrimary() else {
                throw NSError(domain: "BrainScan.Detect", code: -1, userInfo: [
                    NSLocalizedDescriptionKey: "No primary screen"
                ])
            }
            let geometry: [Int: DisplaySnapshot] = [primary.monitorIndex: primary]
            let prepared = try await AnnotationSubmitter.prepare(geometry: geometry)
            guard let snap = prepared[primary.monitorIndex] else {
                throw NSError(domain: "BrainScan.Detect", code: -2, userInfo: [
                    NSLocalizedDescriptionKey: "Capture missing for primary monitor"
                ])
            }
            let screen = try await APIClient.shared.uploadScreenshots(
                images: prepared.mapValues(\.png)
            )
            let resp = try await APIClient.shared.detect(
                screenshotId: screen.id, monitorIndex: snap.monitorIndex
            )
            let result = Self.makeResult(from: resp, snap: snap)
            await MainActor.run { self.presentResult(result) }
        } catch {
            NSLog("[BrainScan] Detect failed: %@", "\(error)")
            await MainActor.run {
                self.longerWork?.cancel()
                self.overlay.showRegionsNotFound()
                self.result = DetectResult(predictions: [])
                self.toolbar.configure(result: self.result!)
                self.positionToolbar()
                self.panel.orderFrontRegardless()
            }
        }
    }

    /// API-bbox (physical px, top-left) → Bbox (logical pt, top-left). Все
    /// рендер-канвасы (DetectOverlayView, BboxCanvasView) — isFlipped=true,
    /// конвенция совпадает с CoordinateConverter.physical. Открыто `static`
    /// для unit-теста.
    static func makeResult(
        from resp: APIClient.DetectResponse, snap: PreparedSnapshot
    ) -> DetectResult {
        let regions = resp.regions.map { Self.toBbox($0.region, snap: snap) }
        let tumors = resp.regions.compactMap {
            $0.tumor.map { Self.toBbox($0, snap: snap) }
        }
        return DetectResult(predictions: [
            DetectPrediction(
                monitorIndex: snap.monitorIndex,
                regions: regions,
                tumors: tumors
            )
        ])
    }

    static func toBbox(
        _ b: APIClient.BBoxResultDTO, snap: PreparedSnapshot
    ) -> Bbox {
        let s = snap.scaleFactor
        let rect = CGRect(
            x: CGFloat(b.x) / s,
            y: CGFloat(b.y) / s,
            width: CGFloat(b.w) / s,
            height: CGFloat(b.h) / s
        )
        return Bbox(rect: rect, monitorIndex: snap.monitorIndex)
    }

    private func presentResult(_ r: DetectResult) {
        longerWork?.cancel()
        result = r
        if r.hasAnyRegion {
            overlay.showResult(r)
        } else {
            overlay.showRegionsNotFound()
        }
        toolbar.configure(result: r)
        positionToolbar()
        panel.orderFrontRegardless()
    }

    // MARK: - Действия

    private func approve() {
        NSLog("[BrainScan] Detect approve (stub): regions=\(result?.predictions.count ?? 0)")
        finish()
    }

    private func edit() {
        guard let prefill = result?.prefillStates() else { finish(); return }
        cancelWork()
        removeKeyMonitor()
        overlay.dismiss()
        panel.orderOut(nil)
        onEdit?(prefill)
    }

    // MARK: - Раскладка (морф «на месте» из позиции виджета)

    private func positionToolbar() {
        let size = toolbar.totalSize()
        let bodyW = size.width - dotOverflow
        let bodyH = size.height - dotOverflow
        let origin = NSPoint(x: bodyCenter.x - bodyW / 2, y: bodyCenter.y - bodyH / 2)
        panel.setFrame(NSRect(origin: origin, size: size), display: true)
        toolbar.needsLayout = true
        toolbar.layoutSubtreeIfNeeded()
    }

    // MARK: - Хоткеи (контекстные)

    private func installKeyMonitor() {
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            self?.handleKey(event) == true ? nil : event
        }
    }

    private func removeKeyMonitor() {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        keyMonitor = nil
    }

    private func handleKey(_ event: NSEvent) -> Bool {
        if event.keyCode == 53 { finish(); return true }   // Esc → Back/Discard
        // ⌘X — Discard (доступно и во время Detecting, и на результатах).
        let cmdOnly = event.modifierFlags
            .intersection([.command, .shift, .option, .control]) == [.command]
        if cmdOnly, event.charactersIgnoringModifiers?.lowercased() == "x" {
            finish(); return true
        }
        guard result != nil else { return false }
        let cmdShift = event.modifierFlags.intersection([.command, .shift]) == [.command, .shift]
        switch event.charactersIgnoringModifiers?.lowercased() {
        case "c" where cmdShift: approve(); return true
        case "e" where cmdShift: edit(); return true
        default: return false
        }
    }

    private func cancelWork() {
        longerWork?.cancel(); longerWork = nil
    }
}
