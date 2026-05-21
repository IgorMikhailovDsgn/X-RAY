import AppKit

/// Управляет окнами оверлея на всех мониторах: делает замороженный снимок,
/// поднимает по окну на каждый дисплей, рендерит bbox из модели и пробрасывает
/// события канваса наверх (в `AnnotateController`). Сам модель не мутирует.
final class OverlayController {
    // События канваса → наружу.
    var onDraw: ((_ rect: CGRect, _ tool: AnnotationTool, _ monitorIndex: Int) -> Void)?
    var onExitDrawMode: (() -> Void)?
    var onSelect: ((UUID?) -> Void)?
    var onUpdate: ((_ id: UUID, _ rect: CGRect) -> Void)?
    var onHover: ((UUID?) -> Void)?
    var onDraftLive: ((CGRect) -> Void)?

    private var windows: [Int: OverlayWindow] = [:]   // monitorIndex → окно
    private(set) var snapshots: [Int: DisplaySnapshot] = [:]
    private var hoveredId: UUID?

    var isPresented: Bool { !windows.isEmpty }

    /// Захват экранов и показ оверлея. Бросает `ScreenCaptureError` при отказе в доступе.
    func present() async throws {
        let snaps = try await ScreenCapturer.captureAll()
        await MainActor.run { self.buildWindows(from: snaps) }
    }

    func dismiss() {
        for window in windows.values { window.orderOut(nil) }
        windows.removeAll()
        snapshots.removeAll()
        hoveredId = nil
    }

    @MainActor
    private func buildWindows(from snaps: [DisplaySnapshot]) {
        for snap in snaps {
            snapshots[snap.monitorIndex] = snap
            let window = OverlayWindow(snapshot: snap)
            wire(window.canvas)
            windows[snap.monitorIndex] = window
            window.orderFrontRegardless()
        }
        windows.values.first?.makeKey()
    }

    private func wire(_ canvas: BboxCanvasView) {
        canvas.onDrawCommitted = { [weak self] rect, tool in
            self?.onDraw?(rect, tool, canvas.monitorIndex)
        }
        canvas.onExitDrawMode = { [weak self] in self?.onExitDrawMode?() }
        canvas.onBboxSelected = { [weak self] id in self?.onSelect?(id) }
        canvas.onBboxUpdated = { [weak self] id, rect in self?.onUpdate?(id, rect) }
        canvas.onHoverBbox = { [weak self] id in
            self?.hoveredId = id
            self?.onHover?(id)
        }
        canvas.onDraftChanged = { [weak self] rect in self?.onDraftLive?(rect) }
    }

    /// Перерисовать оверлей из текущего состояния модели и карты валидации.
    func render(model: AnnotationModel, invalid: [UUID: ValidationError]) {
        let regionBoxes = model.regionState.bboxes.enumerated().map { i, b in
            RenderBox(id: b.id, rect: b.rect, kind: .region, index: i + 1,
                      isInvalid: invalid[b.id] != nil,
                      isActive: b.id == model.activeRegionId || b.id == hoveredId)
        }
        let tumorBoxes = model.tumorState.bboxes.enumerated().map { i, b in
            RenderBox(id: b.id, rect: b.rect, kind: .tumor, index: i + 1,
                      isInvalid: invalid[b.id] != nil,
                      isActive: b.id == model.activeTumorId || b.id == hoveredId)
        }
        let all = regionBoxes + tumorBoxes
        for (monitorIndex, window) in windows {
            window.canvas.activeTool = model.activeTool
            window.canvas.setBoxes(all.filter { boxMonitor($0.id, model) == monitorIndex })
        }
    }

    func highlight(_ id: UUID?) {
        hoveredId = id
    }

    private func boxMonitor(_ id: UUID, _ model: AnnotationModel) -> Int {
        model.allBboxes.first { $0.id == id }?.monitorIndex ?? 0
    }
}
