import AppKit

/// Состояния Default-виджета по Figma «Matrix of widget's status» (36:1843).
/// Реальный source — комбинация `/api/v1/health` + `/api/v1/models/deployed`
/// + локальная sync_queue. Подмена через `DefaultWidgetController.setStatus(_:)`,
/// polling-биндинг придёт в Phase C step 12.
enum WidgetStatus: Equatable {
    /// 🟢 health=ok + models/deployed.count > 0
    case connected(localizerVersion: String, tumorVersion: String)

    /// 🟡 health=ok + локальная очередь не пуста, файлы летят
    case syncing(uploaded: Int, total: Int)

    /// 🟠 health=ok, но models/deployed пустой — Detect недоступен
    case noModels(localAnnotations: Int)

    /// 🔴 health не ответил / network down
    case noServer(localAnnotations: Int)

    /// 🔴 health вернул 5xx
    case serviceUnavailable
}

extension WidgetStatus {
    /// Цвет точки слева от primaryText.
    var dotColor: NSColor {
        switch self {
        case .connected: return .systemGreen
        case .syncing: return .systemYellow
        case .noModels: return .systemOrange
        case .noServer, .serviceUnavailable: return .systemRed
        }
    }

    /// Главная строка индикатора (зеркалит лейблы из Figma).
    var primaryText: String {
        switch self {
        case .connected: return "Server Connected"
        case .syncing: return "Syncing"
        case .noModels: return "Server connected"
        case .noServer: return "No connection with server"
        case .serviceUnavailable: return "Service is not available"
        }
    }

    /// Вторичные строки под главным текстом. Пустой массив → блок не показывается.
    var secondaryLines: [String] {
        switch self {
        case let .connected(localizer, tumor):
            return ["Localizer: \(localizer)", "Tumor Detector: \(tumor)"]
        case let .syncing(uploaded, total):
            return ["\(uploaded)/\(total) screens"]
        case let .noModels(localAnnotations):
            return [
                "Models are not training, use annotate to contribute training data",
                "Local saved annotations: \(localAnnotations)",
            ]
        case let .noServer(localAnnotations):
            return [
                "AI models are not available",
                "Local saved annotations: \(localAnnotations)",
            ]
        case .serviceUnavailable:
            return []
        }
    }

    /// Показывать ⓘ-иконку рядом с primaryText (для проблемных состояний).
    var showsWarningGlyph: Bool {
        switch self {
        case .connected, .syncing, .noModels: return false
        case .noServer, .serviceUnavailable: return true
        }
    }

    /// Detect-кнопка доступна только когда модели задеплоены и сервер отвечает.
    var isDetectEnabled: Bool {
        if case .connected = self { return true }
        return false
    }
}
