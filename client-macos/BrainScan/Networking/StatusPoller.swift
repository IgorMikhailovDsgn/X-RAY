import Foundation

/// Опрашивает `/health` и `/models/deployed` каждые N секунд и публикует
/// серверное состояние. Объединение с `SyncManager.state` (есть ли очередь /
/// идёт дренаж) делает AppDelegate. Эндпоинты публичные — Bearer не требуется.
@MainActor
final class StatusPoller: ObservableObject {
    enum ServerStatus: Equatable {
        case connected(localizerVersion: String, tumorVersion: String)
        case noModels             // /health 200, моделей нет → Detect задизаблен
        case noServer             // network down / отказ соединения
        case serviceUnavailable   // 5xx от /health
    }

    @Published private(set) var serverStatus: ServerStatus = .noServer

    private let api: APIClient
    private let interval: TimeInterval
    private var task: Task<Void, Never>?

    init(api: APIClient = .shared, interval: TimeInterval = 10) {
        self.api = api
        self.interval = interval
    }

    func start() {
        stop()
        task = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                await self.poll()
                try? await Task.sleep(nanoseconds: UInt64(self.interval * 1_000_000_000))
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func poll() async {
        // /health
        do {
            _ = try await api.health()
        } catch let APIError.http(status: code, _) where (500..<600).contains(code) {
            serverStatus = .serviceUnavailable
            return
        } catch {
            serverStatus = .noServer
            return
        }

        // /models/deployed
        do {
            let resp = try await api.modelsDeployed()
            let localizer = resp.models.first { $0.modelType == "localize" }
            let tumor = resp.models.first { $0.modelType == "tumor" }
            if let localizer, let tumor {
                serverStatus = .connected(
                    localizerVersion: localizer.version, tumorVersion: tumor.version
                )
            } else {
                serverStatus = .noModels
            }
        } catch {
            serverStatus = .noServer
        }
    }
}
