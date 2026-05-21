import Foundation

/// Активный инструмент рисования на оверлее.
enum AnnotationTool: Equatable {
    case none
    case addRegion
    case addTumor
}

/// Как открыта сессия разметки — определяет action-маппинг при сохранении.
enum AnnotationEntryMode: Equatable {
    case annotate   // cold start, всё пустое, action = created
    case edit       // после автодетекции, предзаполнено, action = confirmed/corrected
}

/// Состояние сессии разметки: Region + Tumor с каскадными правилами из
/// `docs/brainscan_annotation_mode.md`. Чистая логика, без UI/AppKit —
/// чтобы покрыть юнит-тестами. UI подписывается через `onChange`.
final class AnnotationModel {
    let entryMode: AnnotationEntryMode

    private(set) var regionState: EntityState
    private(set) var tumorState: EntityState
    private(set) var activeTool: AnnotationTool = .none

    /// Активный bbox каждой сущности — на макете плашки Region и Tumor видны
    /// одновременно, поэтому отслеживаем по отдельности (а не один общий).
    private(set) var activeRegionId: UUID?
    private(set) var activeTumorId: UUID?

    /// Невалидные bbox (заполняет ValidationEngine через контроллер). Влияет на Send.
    var invalidBboxIds: Set<UUID> = []

    /// Вызывается после любой мутации состояния — UI перерисовывается.
    var onChange: (() -> Void)?

    init(entryMode: AnnotationEntryMode = .annotate,
         regionState: EntityState = .empty,
         tumorState: EntityState = .empty) {
        self.entryMode = entryMode
        self.regionState = regionState
        self.tumorState = tumorState
    }

    // MARK: - Производные флаги для тулбара

    /// «Опухоль не может существовать без региона» → при Region=null все Tumor-контролы скрыты.
    var tumorControlsEnabled: Bool { !regionState.isNull }

    /// Add Tumor доступен пока Region ≠ null (при empty и bbox — разрешён).
    var addTumorEnabled: Bool { !regionState.isNull }

    /// Mark Null появляется только когда у сущности нет bbox и она не помечена null.
    var markNullRegionVisible: Bool { regionState == .empty }
    var markNullTumorVisible: Bool { tumorState == .empty && tumorControlsEnabled }

    /// Send: обе сущности определены и нет невалидных bbox.
    var sendEnabled: Bool {
        regionState.isDefined && tumorState.isDefined && invalidBboxIds.isEmpty
    }

    var allBboxes: [Bbox] { regionState.bboxes + tumorState.bboxes }

    // MARK: - Активный bbox и навигация

    var activeRegionBbox: Bbox? { regionState.bboxes.first { $0.id == activeRegionId } }
    var activeTumorBbox: Bbox? { tumorState.bboxes.first { $0.id == activeTumorId } }

    /// 1-based индекс активного bbox для маркера навигации (0, если активного нет).
    var activeRegionIndex: Int {
        guard let id = activeRegionId,
              let i = regionState.bboxes.firstIndex(where: { $0.id == id }) else { return 0 }
        return i + 1
    }
    var activeTumorIndex: Int {
        guard let id = activeTumorId,
              let i = tumorState.bboxes.firstIndex(where: { $0.id == id }) else { return 0 }
        return i + 1
    }

    /// Любой bbox можно выбрать кликом на оверлее — выставляем активным в его сущности.
    func select(id: UUID) {
        if regionState.bboxes.contains(where: { $0.id == id }) { activeRegionId = id }
        else if tumorState.bboxes.contains(where: { $0.id == id }) { activeTumorId = id }
        notify()
    }

    func cycleRegion(_ delta: Int) { activeRegionId = cycled(regionState.bboxes, activeRegionId, delta) }
    func cycleTumor(_ delta: Int) { activeTumorId = cycled(tumorState.bboxes, activeTumorId, delta) }

    private func cycled(_ list: [Bbox], _ current: UUID?, _ delta: Int) -> UUID? {
        guard !list.isEmpty,
              let cur = current,
              let i = list.firstIndex(where: { $0.id == cur }) else { return current }
        let next = (i + delta + list.count) % list.count
        defer { notify() }
        return list[next].id
    }

    // MARK: - Инструменты

    func activateAddRegion() {
        activeTool = .addRegion
        notify()
    }

    func activateAddTumor() {
        guard addTumorEnabled else { return }
        activeTool = .addTumor
        notify()
    }

    func cancelTool() {
        guard activeTool != .none else { return }
        activeTool = .none
        notify()
    }

    // MARK: - Коммит нарисованных bbox

    func appendRegionBbox(_ bbox: Bbox) {
        var list = regionState.bboxes
        list.append(bbox)
        regionState = .bboxes(list)
        activeRegionId = bbox.id
        notify()
    }

    func appendTumorBbox(_ bbox: Bbox) {
        guard tumorControlsEnabled else { return }
        var list = tumorState.bboxes
        list.append(bbox)
        tumorState = .bboxes(list)
        activeTumorId = bbox.id
        notify()
    }

    func updateBbox(id: UUID, rect: CGRect) {
        if let i = regionState.bboxes.firstIndex(where: { $0.id == id }) {
            var list = regionState.bboxes
            list[i].rect = rect
            regionState = .bboxes(list)
            notify()
            return
        }
        if let i = tumorState.bboxes.firstIndex(where: { $0.id == id }) {
            var list = tumorState.bboxes
            list[i].rect = rect
            tumorState = .bboxes(list)
            notify()
        }
    }

    // MARK: - Mark Null

    func markNullRegion() {
        regionState = .null
        tumorState = .null   // каскад: опухоль не может существовать без региона
        activeTool = .none
        activeRegionId = nil
        activeTumorId = nil
        notify()
    }

    func markNullTumor() {
        guard tumorControlsEnabled else { return }
        tumorState = .null
        activeTool = .none
        notify()
    }

    // MARK: - Сброс (× и удаление bbox)

    /// × Region или удаление последнего region bbox → Region=empty, Tumor=empty (каскад).
    func clearRegion() {
        regionState = .empty
        tumorState = .empty
        activeTool = .none
        activeRegionId = nil
        activeTumorId = nil
        notify()
    }

    func clearTumor() {
        guard tumorControlsEnabled else { return }
        tumorState = .empty
        activeTumorId = nil
        if activeTool == .addTumor { activeTool = .none }
        notify()
    }

    /// Удаление конкретного bbox по id с применением каскада, если ушёл последний region.
    func removeBbox(id: UUID) {
        if regionState.bboxes.contains(where: { $0.id == id }) {
            let remaining = regionState.bboxes.filter { $0.id != id }
            if remaining.isEmpty {
                clearRegion()          // последний region ушёл → каскадный сброс tumor
            } else {
                regionState = .bboxes(remaining)
                if activeRegionId == id { activeRegionId = remaining.last?.id }
                notify()
            }
            return
        }
        if tumorState.bboxes.contains(where: { $0.id == id }) {
            let remaining = tumorState.bboxes.filter { $0.id != id }
            tumorState = remaining.isEmpty ? .empty : .bboxes(remaining)
            if activeTumorId == id { activeTumorId = remaining.last?.id }
            notify()
        }
    }

    private func notify() { onChange?() }
}
