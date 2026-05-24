import AppKit
import Combine
import Foundation
import Network

/// Оффлайн-очередь разметок. Поток UI Send:
/// - онлайн → пытаемся отправить; на сетевую ошибку складываем в очередь.
/// - оффлайн → сразу в очередь.
/// На восстановлении связи (`NWPathMonitor` → `.satisfied`) запускается дренаж
/// очереди. Публикует `state` для биндинга к статусу виджета (`.syncing(...)`).
@MainActor
final class SyncManager: ObservableObject {
    enum State: Equatable {
        case idle                                  // очередь пуста
        case queued(count: Int)                    // что-то ждёт отправки
        case draining(uploaded: Int, total: Int)   // сейчас отправляем
    }

    /// Результат UI Send'a: пошло на сервер или легло в локальную очередь.
    enum SubmitOutcome { case uploaded, queued }

    static let shared = SyncManager()

    @Published private(set) var state: State = .idle

    private let store: SyncStore
    private let monitor = NWPathMonitor()
    private let monitorQueue = DispatchQueue(label: "brainscan.sync.path")
    private var draining = false
    /// Текущее состояние сети из NWPathMonitor. Стартуем с `true`, чтобы первый Send
    /// сразу пробовал отправку, не дожидаясь первого pathUpdate.
    private var online = true

    init() {
        // Безопасный fallback: если по какой-то причине Application Support недоступен
        // — храним очередь в /tmp на текущий запуск (даём приложению хотя бы работать).
        if let real = try? SyncStore() {
            store = real
        } else {
            preconditionFailure("Failed to initialize SyncStore")
        }
        refreshStateFromDisk()
        monitor.pathUpdateHandler = { [weak self] path in
            let isOnline = path.status == .satisfied
            Task { @MainActor in
                self?.online = isOnline
                if isOnline { await self?.attemptDrain() }
            }
        }
        monitor.start(queue: monitorQueue)
    }

    var isOnline: Bool { online }

    // MARK: - UI Send

    /// Попытка отправить разметку с предзахваченными снимками. Сетевые сбои
    /// и оффлайн → элемент откладывается в очередь, метод возвращается без ошибки
    /// (пользователю отправка «удалась» — она сохранена локально). Возвращает
    /// `SubmitOutcome` чтобы UI мог показать соответствующий toast.
    @discardableResult
    func submitOrQueue(payload: UploadPayload,
                       snapshots: PreparedSnapshots) async throws -> SubmitOutcome {
        if online {
            do {
                try await AnnotationSubmitter.upload(payload: payload, snapshots: snapshots)
                refreshStateFromDisk()
                return .uploaded
            } catch let error as APIError {
                if case .network = error {
                    try persist(payload: payload, snapshots: snapshots)
                    return .queued
                }
                throw error
            }
        } else {
            try persist(payload: payload, snapshots: snapshots)
            return .queued
        }
    }

    // MARK: - Drain

    /// Пройтись по очереди и пытаться отправить каждый элемент. Сетевая ошибка —
    /// останавливаемся (попробуем при следующем onlineEvent). Прочие — удаляем
    /// элемент (испорчен / отклонён бэкендом) и едем дальше.
    ///
    /// Между переходами вставлены небольшие задержки (`minPhaseDuration`) —
    /// иначе на быстром локальном бэкенде drain отрабатывает за ~50мс на элемент,
    /// и пользователь не видит ни одного `.syncing(...)` тика.
    func attemptDrain() async {
        guard !draining, online else { return }
        let items = (try? store.pending()) ?? []
        guard !items.isEmpty else { state = .idle; return }
        draining = true
        defer { draining = false; refreshStateFromDisk() }

        let minPhaseDuration: UInt64 = 350_000_000   // 350мс
        var uploaded = 0
        state = .draining(uploaded: 0, total: items.count)
        try? await Task.sleep(nanoseconds: minPhaseDuration)   // даём UI показать `Syncing 0/N`

        for item in items {
            guard let prepared = loadPrepared(item: item) else {
                try? store.remove(itemID: item.id); continue
            }
            do {
                let started = DispatchTime.now()
                try await AnnotationSubmitter.upload(payload: item.payload, snapshots: prepared)
                try? store.remove(itemID: item.id)
                uploaded += 1
                state = .draining(uploaded: uploaded, total: items.count)
                let elapsed = DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds
                if elapsed < minPhaseDuration {
                    try? await Task.sleep(nanoseconds: minPhaseDuration - elapsed)
                }
            } catch let error as APIError {
                if case .network = error { return }   // ждём следующего онлайна
                NSLog("[Sync] dropping item \(item.id): \(error.localizedDescription)")
                try? store.remove(itemID: item.id)
            } catch {
                NSLog("[Sync] dropping item \(item.id): \(error.localizedDescription)")
                try? store.remove(itemID: item.id)
            }
        }
    }

    // MARK: - Persistence helpers

    private func persist(payload: UploadPayload, snapshots: PreparedSnapshots) throws {
        let monitors = snapshots.map { (index, snap) in
            MonitorMeta(monitorIndex: index, displayID: UInt32(snap.displayID),
                        frame: CodableRect(snap.frame), scaleFactor: Double(snap.scaleFactor))
        }
        let manifest = SyncManifest(id: UUID(), createdAt: Date(),
                                    payload: payload, monitors: monitors)
        let images = snapshots.reduce(into: [Int: Data]()) { dict, kv in
            dict[kv.key] = kv.value.png
        }
        try store.enqueue(manifest: manifest, images: images)
        refreshStateFromDisk()
    }

    private func loadPrepared(item: SyncManifest) -> PreparedSnapshots? {
        var out: PreparedSnapshots = [:]
        for meta in item.monitors {
            guard let png = store.loadImage(itemID: item.id, monitorIndex: meta.monitorIndex),
                  let image = NSBitmapImageRep(data: png)?.cgImage
            else { continue }
            out[meta.monitorIndex] = PreparedSnapshot(
                displayID: CGDirectDisplayID(meta.displayID),
                monitorIndex: meta.monitorIndex,
                frame: meta.frame.cgRect,
                scaleFactor: CGFloat(meta.scaleFactor),
                image: image,
                png: png
            )
        }
        return out.isEmpty ? nil : out
    }

    private func refreshStateFromDisk() {
        let count = store.pendingCount
        state = count == 0 ? .idle : .queued(count: count)
    }
}
